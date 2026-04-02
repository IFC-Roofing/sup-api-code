# Learning API Endpoints for IFC Rails App
# RESTful endpoints to power the learning feedback loop

# =====================================================
# LEARNING CONTROLLER
# =====================================================

class LearningController < ApplicationController
  before_action :authenticate_user!
  before_action :find_project, only: [:project_patterns, :track_outcome]

  # GET /api/learning/patterns?carrier=Allstate&strategies[]=steep_on_waste
  # Returns learned patterns for AI prompt enhancement
  def patterns
    carrier = params[:carrier]
    strategies = params[:strategies] || []
    trade_tags = params[:trade_tags] || []

    if carrier.blank?
      return render json: { error: 'carrier parameter required' }, status: 400
    end

    patterns = LearningPattern.for_context(
      carrier: carrier,
      strategies: strategies,
      trade_tags: trade_tags
    )

    # Format for AI consumption
    pattern_data = {}
    patterns.each do |pattern|
      pattern_data[pattern.context_key] = {
        type: pattern.pattern_type,
        data: pattern.pattern_data,
        confidence: pattern.confidence_score,
        sample_size: pattern.sample_size,
        recommendation: generate_recommendation(pattern)
      }
    end

    render json: {
      carrier: carrier,
      patterns: pattern_data,
      cached_at: Time.current.iso8601,
      expires_in: 1.hour.to_i
    }
  end

  # GET /api/learning/projects/:project_id/patterns
  # Get patterns specific to a project context
  def project_patterns
    carrier = @project.carrier
    recent_strategies = extract_recent_strategies_for_project(@project)

    patterns = LearningPattern.for_context(
      carrier: carrier,
      strategies: recent_strategies,
      trade_tags: @project.action_trackers.pluck(:tag).compact
    )

    render json: {
      project_id: @project.id,
      carrier: carrier,
      patterns: format_patterns_for_api(patterns),
      project_context: {
        recent_strategies: recent_strategies,
        trade_tags: @project.action_trackers.pluck(:tag).compact,
        claim_age_days: (@project.created_at - Time.current).to_i.abs / 1.day
      }
    }
  end

  # POST /api/learning/events
  # Track supplement events for learning
  def create_event
    event_params = params.require(:event).permit(
      :project_id, :event_type, :carrier, :adjuster_name, 
      :amount_requested, :amount_approved, :strategies_used,
      event_data: {}, context_data: {}, outcome_data: {}
    )

    event = SupplementEvent.new(event_params)
    event.user = current_user
    event.event_timestamp = Time.current

    if event.save
      # Process strategies if provided
      process_event_strategies(event, params[:strategies] || [])

      # Check if we should trigger learning
      trigger_learning_if_threshold_met

      render json: {
        success: true,
        event_id: event.id,
        message: 'Event tracked successfully'
      }, status: 201
    else
      render json: {
        success: false,
        errors: event.errors.full_messages
      }, status: 422
    end
  end

  # PUT /api/learning/events/:id/outcome
  # Update event with final outcome (approved/denied/settled)
  def track_outcome
    event = SupplementEvent.find(params[:id])
    
    outcome_params = params.require(:outcome).permit(
      :status, :amount_approved, :settlement_date,
      approved_items: [], denied_items: [], reasons: []
    )

    event.update!(
      status: outcome_params[:status],
      amount_approved: outcome_params[:amount_approved],
      outcome_data: {
        approved_items: outcome_params[:approved_items],
        denied_items: outcome_params[:denied_items], 
        reasons: outcome_params[:reasons],
        settled_at: outcome_params[:settlement_date]
      }
    )

    # Update related strategy outcomes
    update_strategy_outcomes_from_outcome(event, outcome_params)

    render json: {
      success: true,
      event_id: event.id,
      success_rate: event.success_rate,
      message: 'Outcome tracked successfully'
    }
  end

  # GET /api/learning/insights?carrier=Allstate&days=30
  # Get learning insights for team dashboard
  def insights
    carrier = params[:carrier]
    days = (params[:days] || 30).to_i
    
    events = SupplementEvent.recent(days)
    events = events.by_carrier(carrier) if carrier.present?

    insights = {
      summary: {
        total_supplements: events.where(event_type: 'generated').count,
        success_rate: calculate_overall_success_rate(events),
        avg_approval_amount: events.successful.average(:amount_approved)&.round(2),
        response_time_days: calculate_avg_response_time(events)
      },
      top_strategies: get_top_performing_strategies(events),
      carrier_insights: get_carrier_specific_insights(events, carrier),
      recommendations: generate_team_recommendations(events)
    }

    render json: insights
  end

  # GET /api/learning/strategy_performance?strategy=steep_on_waste&carrier=Allstate
  def strategy_performance
    strategy_name = params[:strategy]
    carrier = params[:carrier]
    days = (params[:days] || 90).to_i

    outcomes = StrategyOutcome.joins(:supplement_event)
                             .where(supplement_events: { created_at: days.days.ago.. })

    outcomes = outcomes.for_strategy(strategy_name) if strategy_name.present?
    outcomes = outcomes.where(supplement_events: { carrier: carrier }) if carrier.present?

    performance_data = {
      strategy: strategy_name,
      carrier: carrier,
      time_period_days: days,
      total_attempts: outcomes.count,
      success_rate: outcomes.where(outcome: %w[approved partial]).count.to_f / outcomes.count * 100,
      avg_approved_amount: outcomes.where.not(approved_amount: 0).average(:approved_amount)&.round(2),
      common_denial_reasons: get_common_denial_reasons(outcomes),
      trend_data: get_strategy_trend_data(outcomes)
    }

    render json: performance_data
  end

  private

  def find_project
    @project = Project.find(params[:project_id] || params[:id])
  end

  def generate_recommendation(pattern)
    case pattern.pattern_type
    when 'strategy_success'
      success_rate = pattern.pattern_data['success_rate']
      return 'avoid' if success_rate < 15
      return 'deprioritize' if success_rate < 40
      return 'standard' if success_rate < 80
      'prioritize'
    when 'carrier_behavior'
      denial_rate = pattern.pattern_data['denial_rate']
      return 'aggressive_approach' if denial_rate < 20
      return 'balanced_approach' if denial_rate < 60
      'conservative_approach'
    else
      'standard'
    end
  end

  def format_patterns_for_api(patterns)
    formatted = {}
    patterns.each do |pattern|
      formatted[pattern.context_key] = {
        type: pattern.pattern_type,
        confidence: pattern.confidence_score,
        sample_size: pattern.sample_size,
        data: pattern.pattern_data,
        recommendation: generate_recommendation(pattern),
        last_updated: pattern.last_updated_at&.iso8601
      }
    end
    formatted
  end

  def extract_recent_strategies_for_project(project)
    # Get strategies used in recent supplements for this project
    project.supplement_events
           .recent(90)
           .where.not(strategies_used: nil)
           .flat_map { |event| event.parsed_strategies }
           .uniq
  end

  def process_event_strategies(event, strategies)
    strategies.each do |strategy_data|
      StrategyOutcome.create!(
        supplement_event: event,
        strategy_name: strategy_data[:name],
        trade_tag: strategy_data[:trade_tag],
        strategy_amount: strategy_data[:amount],
        outcome: 'unknown',
        context_snapshot: {
          carrier: event.carrier,
          project_status: event.project.status,
          timestamp: Time.current
        }
      )
    end
  end

  def trigger_learning_if_threshold_met
    recent_events = SupplementEvent.recent(1).count
    if recent_events % 10 == 0  # Every 10 new events
      PatternLearnerJob.perform_later
    end
  end

  def calculate_overall_success_rate(events)
    completed_events = events.where.not(status: 'pending')
    return 0 if completed_events.empty?

    successful = completed_events.successful.count
    (successful.to_f / completed_events.count * 100).round(2)
  end

  def get_top_performing_strategies(events)
    StrategyOutcome.joins(:supplement_event)
                   .where(supplement_event: events)
                   .group(:strategy_name)
                   .group('supplement_events.carrier')
                   .calculate('AVG(CASE WHEN outcome IN (?) THEN 1.0 ELSE 0.0 END) * 100', ['approved', 'partial'])
                   .map { |k, v| { strategy: k[0], carrier: k[1], success_rate: v.round(2) } }
                   .sort_by { |s| -s[:success_rate] }
                   .first(10)
  end

  def get_carrier_specific_insights(events, carrier)
    return {} unless carrier.present?

    carrier_events = events.by_carrier(carrier)
    {
      total_events: carrier_events.count,
      success_rate: calculate_overall_success_rate(carrier_events),
      common_strategies: get_common_strategies_for_carrier(carrier_events),
      avg_response_time: calculate_avg_response_time(carrier_events),
      pattern_confidence: get_pattern_confidence_for_carrier(carrier)
    }
  end

  def generate_team_recommendations(events)
    recommendations = []

    # Low success rate strategies
    poor_strategies = StrategyOutcome.joins(:supplement_event)
                                    .where(supplement_event: events)
                                    .group(:strategy_name)
                                    .having('AVG(CASE WHEN outcome IN (?) THEN 1.0 ELSE 0.0 END) < 0.2', ['approved', 'partial'])
                                    .pluck(:strategy_name)

    poor_strategies.each do |strategy|
      recommendations << {
        type: 'strategy_warning',
        message: "Strategy '#{strategy}' has low success rate - consider alternative approach",
        confidence: 'high'
      }
    end

    # High performing new patterns
    recent_high_performers = LearningPattern.where(discovered_at: 7.days.ago..)
                                          .where('pattern_data @> ?', { success_rate: 85 }.to_json)

    recent_high_performers.each do |pattern|
      recommendations << {
        type: 'opportunity',
        message: "New high-performing strategy discovered: #{pattern.pattern_name}",
        confidence: pattern.confidence_score > 0.8 ? 'high' : 'medium'
      }
    end

    recommendations.first(5)  # Limit to top 5 recommendations
  end
end

# =====================================================
# ROUTES (config/routes.rb)
# =====================================================

# Add to routes.rb:
"""
Rails.application.routes.draw do
  namespace :api do
    namespace :learning do
      resources :patterns, only: [:index] do
        collection do
          get :for_project, path: 'projects/:project_id', action: :project_patterns
        end
      end
      
      resources :events, only: [:create] do
        member do
          put :outcome, action: :track_outcome
        end
      end
      
      get :insights
      get :strategy_performance
    end
  end
end
"""

# =====================================================
# FRONTEND INTEGRATION EXAMPLES
# =====================================================

# JavaScript examples for consuming the learning API:
"""
// Get patterns for supplement generation
async function getPatternsForProject(projectId) {
  const response = await fetch(`/api/learning/patterns/projects/${projectId}`);
  const data = await response.json();
  return data.patterns;
}

// Track supplement generation event
async function trackSupplementGeneration(projectId, strategies, amount) {
  const eventData = {
    event: {
      project_id: projectId,
      event_type: 'generated',
      amount_requested: amount,
      strategies_used: JSON.stringify(strategies),
      event_data: { generated_at: new Date().toISOString() }
    },
    strategies: strategies
  };
  
  const response = await fetch('/api/learning/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(eventData)
  });
  
  return response.json();
}

// Update with insurance response
async function trackInsuranceResponse(eventId, approvedItems, deniedItems) {
  const outcomeData = {
    outcome: {
      status: deniedItems.length === 0 ? 'approved' : 'partial',
      approved_items: approvedItems,
      denied_items: deniedItems
    }
  };
  
  const response = await fetch(`/api/learning/events/${eventId}/outcome`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(outcomeData)
  });
  
  return response.json();
}
"""