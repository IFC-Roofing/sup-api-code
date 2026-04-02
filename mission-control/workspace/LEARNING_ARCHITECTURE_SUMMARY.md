# IFC Learning Architecture — Complete Design
**Automated Feedback Loop for Supplement AI at Scale**

## 🎯 **Executive Summary**

This learning system transforms the IFC supplement process from static AI prompts to **dynamic, self-improving intelligence** that learns from every insurance interaction. The system captures what works, what doesn't, and automatically adjusts strategies to maximize approval rates.

**Key Benefits:**
- **Scales automatically** - Gets smarter with every supplement sent
- **Carrier-specific learning** - Adapts to each insurance company's patterns  
- **Strategy optimization** - Identifies high/low performing approaches
- **Team insights** - Provides actionable recommendations to supplement team

---

## 🏗️ **Architecture Overview**

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Supplement    │───▶│  Learning Engine │───▶│   AI Prompts    │
│   Generation    │    │                  │    │   (Dynamic)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Event Capture  │    │ Pattern Analysis │    │ Strategy Adjust │
│  (Real-time)    │    │   (Nightly)      │    │  (Real-time)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Insurance       │    │ Pattern Storage  │    │ Team Dashboard │
│ Response        │    │  (Database)      │    │  (Insights)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

---

## 🗄️ **Database Design**

### **Core Tables**

**SupplementEvent** - Tracks every supplement interaction
```sql
- project_id, user_id, ai_tool_id
- event_type: 'generated', 'sent', 'response', 'settled'
- status: 'pending', 'approved', 'denied', 'partial'
- amounts: requested, approved
- context: carrier, adjuster, strategies_used
- timeline: event_timestamp, parent_event_id
```

**LearningPattern** - Discovered intelligence  
```sql
- pattern_type: 'carrier_behavior', 'strategy_success', 'adjuster_pattern'
- context_key: 'Allstate_steep_waste', 'State_Farm_O&P'
- pattern_data: JSON with success rates, denial reasons, recommendations
- confidence_score: 0.0 - 1.0 based on sample size
- sample_size: Number of events this pattern is based on
```

**StrategyOutcome** - Links strategies to results
```sql
- supplement_event_id, strategy_name, trade_tag
- outcome: 'approved', 'denied', 'partial'
- amounts: strategy_amount, approved_amount
- denial_reason: Insurance explanation text
```

### **Relationships**
- `Project` → `SupplementEvent` → `StrategyOutcome`
- `LearningPattern` ← discovered from → `SupplementEvent`
- `AiTool` → generates → `SupplementEvent`

---

## 🔄 **Learning Flow**

### **1. Event Capture (Real-time)**
```ruby
# When supplement is generated
SupplementEvent.create!(
  project: project,
  event_type: 'generated',
  strategies_used: ['steep_on_waste', 'full_fence_scope'],
  amount_requested: 32794.58,
  carrier: 'Allstate'
)

# When insurance responds  
SupplementEvent.create!(
  parent_event: generation_event,
  event_type: 'response',
  approved_items: [{ strategy: 'full_fence_scope', amount: 5000 }],
  denied_items: [{ strategy: 'steep_on_waste', reason: 'not covered per guidelines' }]
)
```

### **2. Pattern Discovery (Nightly)**
```ruby
class PatternLearnerJob
  def perform
    # Discover carrier behaviors
    carriers.each do |carrier|
      events = SupplementEvent.by_carrier(carrier).recent(90)
      
      pattern_data = {
        'denial_rate' => events.denied.count.to_f / events.count * 100,
        'common_reasons' => extract_common_denial_reasons(events),
        'avg_response_days' => calculate_response_time(events)
      }
      
      LearningPattern.find_or_create_by(
        pattern_type: 'carrier_behavior',
        context_key: "#{carrier}_general"
      ).incorporate_new_data!(pattern_data, events.count)
    end
    
    # Discover strategy success rates
    # Update AI prompt recommendations
  end
end
```

### **3. Dynamic Application (Real-time)**
```ruby
# AI tools get learned patterns before generating supplements
def self.execute(tool_input, user: nil, project_id: nil)
  project = Project.find(project_id)
  
  # Get learned patterns for this context
  learned_patterns = LearningPattern.for_context(
    carrier: project.carrier,
    strategies: ['steep_on_waste', 'fence_scope'],
    trade_tags: ['@shingle_roof', '@fence']
  )
  
  # Send to Python pipeline with learning context
  response = api_call('/v1/estimate', {
    project_name: project.name,
    learned_patterns: format_patterns_for_ai(learned_patterns)
  })
end
```

---

## 📊 **Learning Examples**

### **Carrier Pattern Discovery**
```json
{
  "pattern_type": "carrier_behavior",
  "context_key": "Allstate_general", 
  "pattern_data": {
    "denial_rate": 73.2,
    "avg_response_days": 8.5,
    "common_reasons": [
      "steep charge not applicable to waste materials",
      "O&P not justified for single trade",
      "pre-loss condition documentation insufficient"
    ],
    "preferred_evidence": ["photos", "EagleView", "contractor_statements"]
  },
  "confidence_score": 0.89,
  "sample_size": 127
}
```

### **Strategy Success Tracking**
```json
{
  "pattern_type": "strategy_success",
  "context_key": "State_Farm_steep_on_waste",
  "pattern_data": {
    "success_rate": 24.3,
    "avg_amount": 1847.50,
    "trend": "declining",
    "last_successful": "2026-02-15",
    "recommendation": "deprioritize"
  },
  "confidence_score": 0.76,
  "sample_size": 89
}
```

---

## 🚀 **Integration with Existing System**

### **AiTool Enhancement**
```ruby
# Existing GenerateSupplementTool enhanced with learning
class GenerateSupplementTool
  def self.execute(tool_input, user: nil, project_id: nil)
    # 1. Capture generation event
    event = create_supplement_event(project_id, user)
    
    # 2. Get learned patterns for this context  
    patterns = get_learned_patterns(project, user)
    
    # 3. Call Python pipeline with learning context
    result = call_sup_api_with_patterns(tool_input, patterns)
    
    # 4. Update event with results and strategies used
    update_event_with_results(event, result)
    
    # 5. Create strategy outcomes for tracking
    create_strategy_outcomes(event, result['strategies_used'])
  end
end
```

### **API Enhancements**
```python
# Flask API updated to consume learned patterns
@app.route('/v1/estimate', methods=['POST']) 
def generate_estimate():
    data = request.get_json()
    learned_patterns = data.get('learned_patterns', {})
    
    # Pass patterns to AI pipeline via environment
    env = os.environ.copy()
    env['LEARNED_PATTERNS'] = json.dumps(learned_patterns)
    
    # AI prompt gets dynamic strategy recommendations
    result = subprocess.run(cmd, env=env)
```

---

## 🎛️ **Team Dashboard Features**

### **Real-time Insights**
- **Success Rate Trends** - By carrier, strategy, time period
- **Strategy Performance** - Which approaches are working/failing  
- **Carrier Intelligence** - Learned behaviors per insurance company
- **Alert System** - "Allstate denying steep charges 90% this month"

### **Actionable Recommendations**  
- **Strategy Suggestions** - "Use fence approach with State Farm"
- **Evidence Recommendations** - "Include EagleView diagrams for Allstate"
- **Timing Insights** - "Chubb responds faster on Tuesdays"
- **Risk Warnings** - "Low success rate for O&P with this adjuster"

### **Learning Confidence**
- **Pattern Strength** - How reliable each insight is
- **Sample Sizes** - How much data supports each recommendation  
- **Trend Analysis** - Whether patterns are improving/declining
- **Human Override** - Team can flag patterns as incorrect

---

## 🔧 **Implementation Phases**

### **Phase 1: Event Capture (Week 1-2)**
- Add database tables to Rails app
- Update existing AiTools to log supplement events
- Create basic pattern storage infrastructure

### **Phase 2: Pattern Discovery (Week 3-4)**  
- Build PatternLearnerJob background processor
- Create pattern analysis algorithms 
- Add confidence scoring and validation

### **Phase 3: Dynamic Integration (Week 5-6)**
- Update Flask API to consume learned patterns
- Enhance AI prompts with dynamic recommendations
- Add pattern-based strategy adjustment

### **Phase 4: Team Interface (Week 7-8)**
- Build learning insights API endpoints
- Create team dashboard with success rates and recommendations
- Add pattern override and human feedback mechanisms

---

## 📈 **Expected Outcomes**

### **Quantitative Improvements**
- **20-40% increase in supplement approval rates** within 6 months
- **15-25% reduction in appraisal escalations** due to better strategy selection
- **30-50% faster supplement preparation** with optimized approaches

### **Qualitative Benefits**
- **Reduced training time** for new team members - AI knows what works
- **Consistent strategy application** across all team members
- **Proactive carrier intelligence** - know what will be denied before sending
- **Competitive advantage** - unique insights other firms don't have

---

## 🛡️ **Risk Mitigation**

### **Data Quality**
- **Minimum sample sizes** before trusting patterns (10+ events)
- **Confidence scoring** to weight pattern reliability
- **Human review gates** for major strategy changes

### **Privacy & Security**  
- **No client PII in learning data** - only strategies and outcomes
- **Anonymized pattern sharing** across projects
- **Secure API endpoints** with authentication

### **Operational Safety**
- **Gradual rollout** with A/B testing  
- **Fallback to static prompts** if learning system fails
- **Human override capabilities** for all recommendations

---

## 🎯 **Success Metrics**

### **Learning System Health**
- **Pattern Discovery Rate** - New insights per week
- **Confidence Scores** - Reliability of learned patterns
- **Coverage** - % of supplements using learned strategies

### **Business Impact**  
- **Supplement Approval Rate** - % approved on first submission
- **Time to Settlement** - Days from supplement to payment
- **Appraisal Avoidance** - % supplements settled without escalation

### **Team Adoption**
- **Strategy Adherence** - % team follows learned recommendations  
- **Feedback Quality** - Human corrections to pattern accuracy
- **Training Reduction** - Time to onboard new supplement specialists

---

**This learning architecture transforms the IFC supplement process from reactive manual work to proactive, data-driven intelligence that continuously improves outcomes for every project.**