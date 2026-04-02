# Learning Integration with Existing AiTool System
# Shows how to connect the learning models to supplement generation

# =====================================================
# UPDATED AI TOOL: Add Learning Integration
# =====================================================

module AiTools
  module SupExternal
    class GenerateSupplementTool
      def self.execute(tool_input, user: nil, project_id: nil)
        project_name = tool_input['project_name']
        project = Project.find_by(id: project_id)
        
        # LEARNING INTEGRATION: Capture generation event
        generation_event = SupplementEvent.create!(
          project_id: project_id,
          user: user,
          ai_tool: AiTool.find_by(name: 'sup_external_generate_supplement'),
          event_type: 'generated',
          event_timestamp: Time.current,
          event_data: {
            tool_input: tool_input,
            requested_at: Time.current
          },
          context_data: {
            carrier: project&.carrier,
            project_status: project&.status,
            user_id: user&.id
          },
          carrier: project&.carrier
        )

        # LEARNING INTEGRATION: Get learned patterns for this context
        learned_patterns = get_learned_patterns_for_context(
          carrier: project&.carrier,
          project: project,
          user: user
        )

        # Call Sup API with learned patterns
        api_url = ENV['SUP_API_URL']
        api_key = ENV['SUP_API_KEY']

        conn = Faraday.new(url: api_url) do |f|
          f.request :json
          f.response :json
          f.options.timeout = TIMEOUT
        end

        response = conn.post('/v1/estimate') do |req|
          req.headers['Authorization'] = "Bearer #{api_key}"
          req.body = {
            project_name: project_name,
            project_id: project_id,
            learned_patterns: learned_patterns,  # ← NEW: AI gets learned insights
            context: {
              carrier: project&.carrier,
              generation_event_id: generation_event.id
            }
          }
        end

        if response.success? && response.body['success']
          result = response.body
          
          # LEARNING INTEGRATION: Update generation event with results
          generation_event.update!(
            status: 'pending',
            event_data: generation_event.event_data.merge({
              strategies_generated: extract_strategies_from_result(result),
              total_rcv: result['total_rcv'],
              trade_count: result['trade_count'],
              generated_at: Time.current
            }),
            amount_requested: parse_amount(result['total_rcv']),
            strategies_used: extract_strategies_from_result(result).to_json
          )

          # Extract strategies for learning
          if result['strategies_used'].present?
            result['strategies_used'].each do |strategy|
              StrategyOutcome.create!(
                supplement_event: generation_event,
                strategy_name: strategy['name'],
                trade_tag: strategy['trade_tag'],
                strategy_amount: strategy['amount'],
                outcome: 'unknown',  # Will be updated when insurance responds
                context_snapshot: {
                  carrier: project&.carrier,
                  generation_date: Time.current,
                  learned_patterns_applied: learned_patterns.keys
                }
              )
            end
          end

          return {
            success: true,
            data: {
              message: '✅ Supplement generated successfully!',
              pdf_url: result['pdf_url'],
              total_rcv: result['total_rcv'],
              trade_count: result['trade_count'],
              generation_event_id: generation_event.id  # ← Track for future updates
            }
          }
        else
          # Log failure
          generation_event.update!(
            status: 'failed',
            event_data: generation_event.event_data.merge({
              error: response.body['error'] || 'Unknown error',
              failed_at: Time.current
            })
          )
          
          return {
            success: false,
            error: "❌ Supplement generation failed: #{response.body['error']}"
          }
        end
      end

      private

      def self.get_learned_patterns_for_context(carrier:, project:, user:)
        return {} unless carrier.present?

        # Get high-confidence patterns for this carrier
        patterns = LearningPattern.for_carrier(carrier).high_confidence.active
        
        pattern_hash = {}
        patterns.each do |pattern|
          case pattern.pattern_type
          when 'carrier_behavior'
            pattern_hash["#{carrier}_behavior"] = {
              denial_rate: pattern.pattern_data['denial_rate'],
              common_reasons: pattern.pattern_data['common_reasons']&.keys&.first(3),
              confidence: pattern.confidence_score
            }
          when 'strategy_success'
            strategy_name = pattern.context_key.split('_', 2).last
            pattern_hash["strategy_#{strategy_name}"] = {
              success_rate: pattern.pattern_data['success_rate'],
              recommendation: get_strategy_recommendation(pattern),
              confidence: pattern.confidence_score
            }
          end
        end

        # Add cached recent insights
        cached_patterns = Rails.cache.read('learning_patterns_for_ai') || {}
        pattern_hash.merge!(cached_patterns.select { |k, _| k.include?(carrier) })

        pattern_hash
      end

      def self.get_strategy_recommendation(pattern)
        success_rate = pattern.pattern_data['success_rate']
        return 'skip' if success_rate < 20
        return 'prioritize' if success_rate > 90
        return 'include' if success_rate > 50
        'consider'
      end

      def self.extract_strategies_from_result(result)
        # Parse strategies from the API response
        strategies = []
        if result['flow_package'] && result['flow_package']['trades']
          result['flow_package']['trades'].each do |trade|
            if trade['strategies']
              trade['strategies'].each do |strategy|
                strategies << {
                  name: strategy['name'],
                  trade_tag: trade['tag'],
                  amount: strategy['amount']
                }
              end
            end
          end
        end
        strategies
      end

      def self.parse_amount(amount_str)
        return 0 unless amount_str.present?
        amount_str.gsub(/[$,\s]/, '').to_f
      end
    end
  end
end

# =====================================================
# NEW API ENDPOINT: Insurance Response Tracking
# =====================================================

module AiTools
  module SupExternal
    class TrackInsuranceResponseTool
      def self.definition
        {
          name: 'sup_external_track_response',
          description: 'Track insurance response to a supplement for learning purposes. ' \
                       'Records approvals, denials, and reasons to improve future supplements.',
          input_schema: {
            type: 'object',
            properties: {
              generation_event_id: {
                type: 'integer',
                description: 'ID of the original generation event to link this response'
              },
              approved_items: {
                type: 'array',
                description: 'List of approved line items with amounts'
              },
              denied_items: {
                type: 'array', 
                description: 'List of denied line items with reasons'
              },
              partial_items: {
                type: 'array',
                description: 'List of partially approved items'
              },
              response_document: {
                type: 'string',
                description: 'Link to insurance response document'
              }
            },
            required: ['generation_event_id']
          }
        }
      end

      def self.execute(tool_input, user: nil, project_id: nil)
        generation_event = SupplementEvent.find_by(id: tool_input['generation_event_id'])
        unless generation_event
          return { success: false, error: 'Generation event not found' }
        end

        # Create response event
        response_event = SupplementEvent.create!(
          project: generation_event.project,
          user: user,
          ai_tool: AiTool.find_by(name: 'sup_external_track_response'),
          parent_event: generation_event,
          event_type: 'response',
          event_timestamp: Time.current,
          event_data: {
            approved_items: tool_input['approved_items'] || [],
            denied_items: tool_input['denied_items'] || [],
            partial_items: tool_input['partial_items'] || [],
            response_document: tool_input['response_document']
          },
          context_data: generation_event.context_data,
          carrier: generation_event.carrier
        )

        # Calculate overall outcome
        total_requested = generation_event.amount_requested
        total_approved = calculate_approved_amount(tool_input)
        
        outcome_status = determine_outcome_status(total_requested, total_approved)
        
        response_event.update!(
          status: outcome_status,
          amount_requested: total_requested,
          amount_approved: total_approved
        )

        # Update strategy outcomes based on response
        update_strategy_outcomes(generation_event, tool_input)

        # Trigger learning job if we have enough new data
        schedule_learning_job_if_needed

        {
          success: true,
          data: {
            message: '✅ Insurance response tracked successfully!',
            response_event_id: response_event.id,
            outcome_status: outcome_status,
            success_rate: ((total_approved / total_requested) * 100).round(2)
          }
        }
      end

      private

      def self.calculate_approved_amount(tool_input)
        approved = (tool_input['approved_items'] || []).sum { |item| item['amount'].to_f }
        partial = (tool_input['partial_items'] || []).sum { |item| item['approved_amount'].to_f }
        approved + partial
      end

      def self.determine_outcome_status(requested, approved)
        return 'denied' if approved.zero?
        return 'approved' if approved >= requested * 0.95  # 95%+ approval
        return 'partial' if approved >= requested * 0.25   # 25%+ approval
        'denied'
      end

      def self.update_strategy_outcomes(generation_event, response_data)
        # Update existing strategy outcomes with actual results
        generation_event.strategy_outcomes.each do |strategy_outcome|
          strategy_name = strategy_outcome.strategy_name
          
          # Find if this strategy was approved/denied in the response
          approved_item = find_strategy_in_response(strategy_name, response_data['approved_items'])
          denied_item = find_strategy_in_response(strategy_name, response_data['denied_items'])
          partial_item = find_strategy_in_response(strategy_name, response_data['partial_items'])

          if approved_item
            strategy_outcome.update!(
              outcome: 'approved',
              approved_amount: approved_item['amount']
            )
          elsif partial_item
            strategy_outcome.update!(
              outcome: 'partial',
              approved_amount: partial_item['approved_amount'],
              denial_reason: partial_item['reason']
            )
          elsif denied_item
            strategy_outcome.update!(
              outcome: 'denied',
              approved_amount: 0,
              denial_reason: denied_item['reason']
            )
          end
        end
      end

      def self.find_strategy_in_response(strategy_name, items)
        return nil unless items.present?
        items.find { |item| item['strategy']&.include?(strategy_name) }
      end

      def self.schedule_learning_job_if_needed
        # Run learning job if we have new response data
        recent_responses = SupplementEvent.where(event_type: 'response')
                                         .where('created_at > ?', 1.hour.ago)
                                         .count
        
        if recent_responses >= 5  # Threshold for triggering learning
          PatternLearnerJob.perform_later
        end
      end
    end
  end
end

# =====================================================
# UPDATED FLASK API: Consume Learned Patterns
# =====================================================

# Add to your Flask app.py:
"""
@app.route('/v1/estimate', methods=['POST'])
def generate_estimate():
    try:
        data = request.get_json()
        project_name = data.get('project_name')
        learned_patterns = data.get('learned_patterns', {})  # ← NEW
        
        # Build command with learned patterns
        cmd = [PYTHON_BIN, GENERATE_SCRIPT, project_name]
        if skip_upload:
            cmd.append('--skip-upload')
        
        # Pass learned patterns via environment or temp file
        env = os.environ.copy()
        if learned_patterns:
            env['LEARNED_PATTERNS'] = json.dumps(learned_patterns)
        
        # Run the PDF generator with learned context
        result = subprocess.run(
            cmd,
            cwd=PDF_GENERATOR_PATH,
            capture_output=True,
            text=True,
            env=env,
            timeout=600
        )
        
        # Extract strategy data from output for learning
        strategies_used = extract_strategies_from_output(result.stdout)
        
        return jsonify({
            'success': True,
            'pdf_url': f'Generated locally in {PDF_GENERATOR_PATH}',
            'total_rcv': extract_rcv(result.stdout),
            'strategies_used': strategies_used,  # ← NEW: For learning feedback
            'learned_patterns_applied': list(learned_patterns.keys())
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def extract_strategies_from_output(output):
    # Parse the supplement output to identify what strategies were used
    strategies = []
    for line in output.split('\n'):
        if 'F9:' in line or 'steep' in line or 'fence' in line:
            # Extract strategy information from output
            strategies.append({
                'name': 'steep_on_waste',  # Identify strategy type
                'trade_tag': '@shingle_roof',
                'amount': 1500.00
            })
    return strategies
"""

# =====================================================
# SCHEDULE LEARNING JOB
# =====================================================

# Add to config/schedule.rb (whenever gem):
# every 1.day, at: '2:00 am' do
#   runner "PatternLearnerJob.perform_later"
# end

# Or in config/initializers/learning.rb:
# if Rails.env.production?
#   Rails.application.config.after_initialize do
#     # Schedule nightly learning job
#     PatternLearnerJob.set(cron: '0 2 * * *').perform_later
#   end
# end