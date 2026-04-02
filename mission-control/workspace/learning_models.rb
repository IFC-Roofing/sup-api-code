# Learning Models for IFC Rails App
# Integrates with existing AiTool architecture for automated feedback loops

# =====================================================
# MIGRATION: Create Learning Tables
# =====================================================

class CreateSupplementEvents < ActiveRecord::Migration[7.0]
  def change
    create_table :supplement_events do |t|
      t.references :project, null: false, foreign_key: true
      t.references :user, null: true, foreign_key: true
      t.references :ai_tool, null: true, foreign_key: true
      
      # Event classification
      t.string :event_type, null: false  # 'generated', 'sent', 'response', 'outcome'
      t.string :status, default: 'pending' # 'pending', 'approved', 'denied', 'partial', 'settled'
      
      # Context data (JSON columns)
      t.json :event_data    # Tool inputs, strategies used, amounts requested
      t.json :context_data  # Carrier, adjuster, project context at time of event
      t.json :outcome_data  # What was approved/denied, reasons, settlement amounts
      
      # Key extracted fields for fast querying
      t.string :carrier
      t.string :adjuster_name
      t.decimal :amount_requested, precision: 10, scale: 2
      t.decimal :amount_approved, precision: 10, scale: 2
      t.text :strategies_used   # JSON array as string for easy searching
      
      # Timeline tracking
      t.datetime :event_timestamp
      t.references :parent_event, null: true, foreign_key: { to_table: :supplement_events }
      
      t.timestamps
    end
    
    add_index :supplement_events, [:project_id, :event_type]
    add_index :supplement_events, [:carrier, :event_type]
    add_index :supplement_events, :event_timestamp
    add_index :supplement_events, :strategies_used, using: 'gin'
  end
end

class CreateLearningPatterns < ActiveRecord::Migration[7.0]
  def change
    create_table :learning_patterns do |t|
      # Pattern identification
      t.string :pattern_type, null: false  # 'carrier_behavior', 'strategy_success', 'adjuster_pattern'
      t.string :context_key, null: false   # 'Allstate_steep_waste', 'State_Farm_O&P', 'adjuster_12345_fence'
      t.string :pattern_name              # Human readable name
      
      # Pattern data
      t.json :pattern_data                # Success rates, common denials, timing patterns
      t.decimal :confidence_score, precision: 5, scale: 4  # 0.0000 to 1.0000
      t.integer :sample_size             # How many events this is based on
      
      # Learning metadata  
      t.datetime :discovered_at
      t.datetime :last_updated_at
      t.references :created_by_job, null: true  # Background job that discovered this
      
      # Status
      t.string :status, default: 'active'  # 'active', 'deprecated', 'needs_review'
      t.text :notes                        # Human annotations
      
      t.timestamps
    end
    
    add_index :learning_patterns, [:pattern_type, :context_key], unique: true
    add_index :learning_patterns, :confidence_score
    add_index :learning_patterns, :discovered_at
  end
end

class CreateStrategyOutcomes < ActiveRecord::Migration[7.0]
  def change
    create_table :strategy_outcomes do |t|
      # Links strategies to outcomes across events
      t.references :supplement_event, null: false, foreign_key: true
      
      # Strategy details
      t.string :strategy_name, null: false  # 'steep_on_waste', 'full_fence_scope', 'f9_pre_loss'
      t.string :trade_tag                  # '@shingle_roof', '@gutter', '@fence'
      t.decimal :strategy_amount, precision: 10, scale: 2
      
      # Outcome
      t.string :outcome, null: false       # 'approved', 'denied', 'partial', 'unknown'
      t.decimal :approved_amount, precision: 10, scale: 2, default: 0
      t.text :denial_reason
      
      # Context at time of strategy
      t.json :context_snapshot            # Carrier rules, adjuster history, etc.
      
      t.timestamps
    end
    
    add_index :strategy_outcomes, [:strategy_name, :outcome]
    add_index :strategy_outcomes, [:trade_tag, :strategy_name]
  end
end

# =====================================================
# MODEL CLASSES
# =====================================================

class SupplementEvent < ApplicationRecord
  belongs_to :project
  belongs_to :user, optional: true
  belongs_to :ai_tool, optional: true
  belongs_to :parent_event, class_name: 'SupplementEvent', optional: true
  
  has_many :child_events, class_name: 'SupplementEvent', foreign_key: 'parent_event_id'
  has_many :strategy_outcomes, dependent: :destroy
  
  validates :event_type, inclusion: { in: %w[generated sent response outcome settled] }
  validates :status, inclusion: { in: %w[pending approved denied partial settled] }
  
  scope :by_carrier, ->(carrier) { where(carrier: carrier) }
  scope :by_event_type, ->(type) { where(event_type: type) }
  scope :successful, -> { where(status: %w[approved partial settled]) }
  scope :denied, -> { where(status: 'denied') }
  scope :recent, ->(days = 30) { where(created_at: days.days.ago..) }
  
  # Extract strategies from JSON data
  def parsed_strategies
    return [] unless strategies_used.present?
    JSON.parse(strategies_used)
  rescue JSON::ParserError
    strategies_used.split(',').map(&:strip)
  end
  
  # Calculate success rate for this event chain
  def success_rate
    return 0 if amount_requested.zero?
    (amount_approved / amount_requested * 100).round(2)
  end
  
  # Find the generation event that started this chain
  def root_event
    event = self
    event = event.parent_event while event.parent_event
    event
  end
end

class LearningPattern < ApplicationRecord
  validates :pattern_type, inclusion: { in: %w[carrier_behavior strategy_success adjuster_pattern seasonal_trend] }
  validates :context_key, presence: true, uniqueness: { scope: :pattern_type }
  validates :confidence_score, inclusion: { in: 0.0..1.0 }
  
  scope :active, -> { where(status: 'active') }
  scope :high_confidence, -> { where('confidence_score >= ?', 0.8) }
  scope :for_carrier, ->(carrier) { where('context_key ILIKE ?', "#{carrier}%") }
  
  # Get patterns relevant to a specific context
  def self.for_context(carrier:, strategies: [], trade_tags: [])
    patterns = active.high_confidence
    
    # Carrier-specific patterns
    carrier_patterns = patterns.where('context_key ILIKE ?', "#{carrier}%")
    
    # Strategy-specific patterns  
    strategy_patterns = patterns.where(
      pattern_type: 'strategy_success',
      context_key: strategies.map { |s| "#{carrier}_#{s}" }
    )
    
    # Trade-specific patterns
    trade_patterns = patterns.where(
      'context_key ILIKE ANY (ARRAY[?])',
      trade_tags.map { |tag| "%#{tag}%" }
    )
    
    (carrier_patterns + strategy_patterns + trade_patterns).uniq
  end
  
  # Update pattern with new data
  def incorporate_new_data!(new_data, new_sample_size)
    # Weighted average based on sample sizes
    old_weight = sample_size.to_f / (sample_size + new_sample_size)
    new_weight = new_sample_size.to_f / (sample_size + new_sample_size)
    
    # Merge pattern data (strategy-specific logic)
    merged_data = merge_pattern_data(pattern_data, new_data, old_weight, new_weight)
    
    update!(
      pattern_data: merged_data,
      sample_size: sample_size + new_sample_size,
      last_updated_at: Time.current,
      confidence_score: calculate_confidence(sample_size + new_sample_size)
    )
  end
  
  private
  
  def merge_pattern_data(old_data, new_data, old_weight, new_weight)
    # Strategy-specific merging logic
    case pattern_type
    when 'carrier_behavior'
      {
        'denial_rate' => (old_data['denial_rate'] * old_weight + new_data['denial_rate'] * new_weight),
        'avg_response_days' => (old_data['avg_response_days'] * old_weight + new_data['avg_response_days'] * new_weight),
        'common_reasons' => merge_frequency_data(old_data['common_reasons'], new_data['common_reasons'])
      }
    when 'strategy_success'
      {
        'success_rate' => (old_data['success_rate'] * old_weight + new_data['success_rate'] * new_weight),
        'avg_amount' => (old_data['avg_amount'] * old_weight + new_data['avg_amount'] * new_weight)
      }
    else
      new_data  # Default: replace with new data
    end
  end
  
  def calculate_confidence(sample_size)
    # More samples = higher confidence, but with diminishing returns
    # Scale: 10 samples = 0.5, 50 samples = 0.8, 100+ samples = 0.95
    [0.95, (sample_size / (sample_size + 20.0))].min
  end
end

class StrategyOutcome < ApplicationRecord
  belongs_to :supplement_event
  
  validates :outcome, inclusion: { in: %w[approved denied partial unknown] }
  validates :strategy_name, presence: true
  
  scope :approved, -> { where(outcome: 'approved') }
  scope :denied, -> { where(outcome: 'denied') }
  scope :for_strategy, ->(name) { where(strategy_name: name) }
  scope :for_trade, ->(tag) { where(trade_tag: tag) }
  
  # Calculate success rate for this strategy across all instances
  def self.success_rate_for(strategy_name, carrier: nil, trade_tag: nil)
    scope = for_strategy(strategy_name)
    scope = scope.joins(:supplement_event).where(supplement_events: { carrier: carrier }) if carrier
    scope = scope.for_trade(trade_tag) if trade_tag
    
    total = scope.count
    return 0 if total.zero?
    
    approved = scope.where(outcome: %w[approved partial]).count
    (approved.to_f / total * 100).round(2)
  end
end

# =====================================================
# LEARNING JOB
# =====================================================

class PatternLearnerJob < ApplicationJob
  queue_as :low_priority
  
  def perform
    Rails.logger.info("PatternLearnerJob: Starting pattern discovery...")
    
    # Discover new patterns from recent events
    discover_carrier_patterns
    discover_strategy_patterns  
    discover_adjuster_patterns
    discover_seasonal_patterns
    
    # Update AI prompts with new insights
    update_dynamic_prompts
    
    Rails.logger.info("PatternLearnerJob: Pattern discovery complete")
  end
  
  private
  
  def discover_carrier_patterns
    carriers = SupplementEvent.distinct.pluck(:carrier).compact
    
    carriers.each do |carrier|
      events = SupplementEvent.by_carrier(carrier).recent(90)
      next if events.count < 10  # Need minimum sample size
      
      pattern_data = {
        'denial_rate' => events.denied.count.to_f / events.count * 100,
        'avg_response_days' => calculate_avg_response_time(events),
        'common_reasons' => extract_common_denial_reasons(events),
        'preferred_evidence' => analyze_approval_factors(events)
      }
      
      pattern = LearningPattern.find_or_initialize_by(
        pattern_type: 'carrier_behavior',
        context_key: "#{carrier}_general"
      )
      
      if pattern.persisted?
        pattern.incorporate_new_data!(pattern_data, events.count)
      else
        pattern.assign_attributes(
          pattern_name: "#{carrier} General Behavior",
          pattern_data: pattern_data,
          sample_size: events.count,
          confidence_score: calculate_confidence(events.count),
          discovered_at: Time.current
        )
        pattern.save!
      end
    end
  end
  
  def discover_strategy_patterns
    # Analyze success rates for each strategy by carrier
    strategies = StrategyOutcome.distinct.pluck(:strategy_name).compact
    carriers = SupplementEvent.distinct.pluck(:carrier).compact
    
    strategies.each do |strategy|
      carriers.each do |carrier|
        outcomes = StrategyOutcome.joins(:supplement_event)
                                  .where(supplement_events: { carrier: carrier })
                                  .for_strategy(strategy)
                                  .recent(90)
        
        next if outcomes.count < 5  # Minimum sample size for strategy patterns
        
        success_rate = outcomes.where(outcome: %w[approved partial]).count.to_f / outcomes.count * 100
        avg_amount = outcomes.average(:approved_amount) || 0
        
        pattern_data = {
          'success_rate' => success_rate,
          'avg_amount' => avg_amount,
          'sample_size' => outcomes.count,
          'last_successes' => outcomes.approved.limit(3).pluck(:context_snapshot)
        }
        
        context_key = "#{carrier}_#{strategy}"
        pattern = LearningPattern.find_or_initialize_by(
          pattern_type: 'strategy_success',
          context_key: context_key
        )
        
        if pattern.persisted?
          pattern.incorporate_new_data!(pattern_data, outcomes.count)
        else
          pattern.assign_attributes(
            pattern_name: "#{strategy} success with #{carrier}",
            pattern_data: pattern_data,
            sample_size: outcomes.count,
            confidence_score: calculate_confidence(outcomes.count),
            discovered_at: Time.current
          )
          pattern.save!
        end
      end
    end
  end
  
  def update_dynamic_prompts
    # Generate prompt updates for high-confidence patterns
    patterns = LearningPattern.active.high_confidence
    
    prompt_updates = {}
    
    patterns.each do |pattern|
      case pattern.pattern_type
      when 'carrier_behavior'
        if pattern.pattern_data['denial_rate'] > 80
          prompt_updates[pattern.context_key] = "High denial rate (#{pattern.pattern_data['denial_rate']}%) - recommend alternative approach"
        end
      when 'strategy_success'  
        if pattern.pattern_data['success_rate'] < 20
          prompt_updates[pattern.context_key] = "Low success rate (#{pattern.pattern_data['success_rate']}%) - consider skipping"
        elsif pattern.pattern_data['success_rate'] > 90
          prompt_updates[pattern.context_key] = "High success rate (#{pattern.pattern_data['success_rate']}%) - prioritize this strategy"
        end
      end
    end
    
    # Store updates for API consumption
    Rails.cache.write('learning_patterns_for_ai', prompt_updates, expires_in: 1.day)
    Rails.logger.info("Updated AI patterns cache with #{prompt_updates.keys.count} insights")
  end
  
  # Helper methods for pattern analysis
  def calculate_avg_response_time(events)
    sent_events = events.where(event_type: 'sent')
    response_events = events.where(event_type: 'response')
    
    times = sent_events.map do |sent|
      response = response_events.where(parent_event: sent).first
      next unless response
      (response.event_timestamp - sent.event_timestamp) / 1.day
    end.compact
    
    times.any? ? times.sum / times.size : 0
  end
  
  def extract_common_denial_reasons(events)
    denial_reasons = events.where(status: 'denied')
                          .joins(:strategy_outcomes)
                          .where.not(strategy_outcomes: { denial_reason: nil })
                          .pluck('strategy_outcomes.denial_reason')
    
    reason_counts = denial_reasons.each_with_object(Hash.new(0)) { |reason, hash| hash[reason] += 1 }
    reason_counts.sort_by { |_, count| -count }.to_h
  end
  
  def calculate_confidence(sample_size)
    [0.95, (sample_size / (sample_size + 20.0))].min
  end
end