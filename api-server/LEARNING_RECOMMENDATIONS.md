# Learning Recommendations Framework
**Intelligence-Driven Supplement Strategy (Not Rule-Based)**

## 🎯 **Core Principle**
**The learning system provides INTELLIGENCE and RECOMMENDATIONS, never automatic decisions to skip strategies.**

The team always decides what to fight for. The AI provides insights on:
- **What approaches work better**
- **What evidence is more persuasive** 
- **What timing/presentation gets better results**
- **What alternative angles to try**

---

## 🧠 **Recommendation Types**

### **1. Approach Intelligence**
```json
{
  "strategy": "steep_on_waste",
  "carrier": "Allstate", 
  "success_rate": 15,
  "recommendation": "needs_better_approach",
  "insights": {
    "current_approach": "Standard F9: 'Steep roof requires additional labor'",
    "better_approaches": [
      "EagleView diagram showing actual roof pitch measurements",
      "Contractor statement about safety equipment requirements",
      "Time study comparison: flat vs steep installation"
    ],
    "successful_examples": [
      "Won with detailed safety equipment justification (Project: Smith, $2,400)"
    ]
  }
}
```

### **2. Evidence Intelligence**
```json
{
  "strategy": "O&P",
  "carrier": "State_Farm",
  "success_rate": 87,
  "recommendation": "current_approach_working", 
  "insights": {
    "winning_evidence": [
      "Multi-trade coordination documentation",
      "Physical office lease/business license", 
      "Employee count verification"
    ],
    "timing": "Submit with initial supplement, not in rebuttal",
    "amount_sweet_spot": "10-15% of total project cost"
  }
}
```

### **3. Presentation Intelligence**
```json
{
  "strategy": "full_fence_scope",
  "carrier": "Allstate",
  "success_rate": 65,
  "recommendation": "standard_approach",
  "insights": {
    "effective_arguments": [
      "Pre-loss condition: partial staining creates visual mismatch",
      "Code requirement: matching appearance standards"  
    ],
    "photo_requirements": [
      "Full fence panoramic shot showing existing condition",
      "Close-up of damaged vs undamaged sections"
    ],
    "denial_counters": {
      "only_damaged_sections": "Matching appearance code reference",
      "homeowner_choice": "Insurance restoration standard citation"
    }
  }
}
```

---

## 📊 **Dashboard Insights**

### **Team Intelligence View:**
```
🎯 ALLSTATE SUPPLEMENT INTELLIGENCE

📈 Overall Success Rate: 67% (↑5% this month)

🔍 Strategy Insights:
├── O&P: 23% success → TRY DIFFERENT APPROACH
│   ✅ What works: Multi-trade documentation + business license
│   ❌ What fails: Single trade O&P without justification
│   💡 Recommendation: Include trade coordination timeline
│
├── Steep on Waste: 15% success → NEEDS BETTER EVIDENCE  
│   ✅ What works: EagleView pitch diagrams
│   ❌ What fails: Generic "steep roof" F9 notes
│   💡 Recommendation: Safety equipment cost breakdown
│
└── Fence Scope: 78% success → CURRENT APPROACH WORKING
    ✅ What works: Pre-loss condition argument + photos
    💡 Keep doing: Full fence photos + matching standard citations

🚨 Recent Pattern Changes:
- Allstate started requesting itemized bids more often (last 2 weeks)
- O&P denials increased 15% - adjust justification approach
```

### **Project-Specific Intelligence:**
```
📋 ROSE BROCK PROJECT - ALLSTATE

🎯 Recommended Approach Based on Learning:

Roof Scope ($26,817):
├── ✅ STRONG APPROACH: Use EagleView measurements + contractor bid
├── 💡 ADD: Tear-off justification with domino effect explanation  
└── 📸 PHOTOS: Include access difficulty shots for this specific address

O&P ($5,256):
├── ⚠️  CHALLENGING: Allstate 23% approval rate for O&P
├── 💡 TRY: Multi-trade coordination angle (roof + gutter + paint)
├── 📋 INCLUDE: Business license + 3-trade timeline documentation
└── ⏰ TIMING: Submit with initial estimate, not rebuttal

Steep Charges ($1,500):
├── ⚠️  DIFFICULT: 15% success rate with standard approach
├── 💡 NEW ANGLE: Safety equipment rental receipts
├── 📋 EVIDENCE: OSHA compliance documentation
└── 📸 PHOTOS: Actual roof pitch measurement with digital level
```

---

## 🔄 **Learning Flow (Recommendations Only)**

### **Before Supplement:**
```
Team: "Generate supplement for Allstate project"

AI Intelligence:
├── Historical data: O&P gets denied 77% with standard F9
├── Recommendation: Try multi-trade coordination angle instead
├── Evidence: Include business license + employee verification
└── Note: This is guidance based on patterns, team decides final approach
```

### **After Insurance Response:**
```
Team: "Insurance denied O&P, approved roof scope"

Learning System Updates:
├── Pattern: Standard O&P approach failed again with Allstate  
├── Insight: Multi-trade projects might have better success rate
├── Next Recommendation: Try coordination timeline documentation
└── Team Decision: Whether to appeal, try different angle, or accept
```

### **Future Projects:**
```
Team: "Generate supplement for another Allstate project"

AI Intelligence:
├── Updated insight: O&P success rate now 18% with standard approach
├── Better approach: Coordination timeline + business documentation 
├── Recent win: Smith project succeeded with safety compliance angle
└── Recommendation: Try coordination approach, but team decides
```

---

## 🎛️ **Implementation Changes**

### **1. Language Changes**
❌ **Old:** "Skipping steep_on_waste (low success rate)"  
✅ **New:** "Steep charges: 15% success rate. Recommend EagleView diagram approach instead of generic F9"

❌ **Old:** "Avoiding O&P for single trade"  
✅ **New:** "O&P challenging for single trade (23% success). Consider multi-trade coordination angle"

### **2. API Response Format**
```json
{
  "intelligence_provided": {
    "Allstate_steep_waste": {
      "type": "approach_recommendation",
      "current_success_rate": 15,
      "recommendation": "Try safety equipment documentation instead of generic steep justification",
      "evidence_suggestions": ["OSHA compliance docs", "Equipment rental receipts"]
    }
  }
}
```

### **3. Team Dashboard**
- **"Strategy Performance"** (not "strategies to avoid")
- **"Recommended Approaches"** (not "blocked strategies") 
- **"Evidence That Works"** (not "denial patterns")
- **"Alternative Angles"** (not "skip recommendations")

---

## 💡 **Philosophy**

### **Learning System Says:**
- "Based on 50 similar projects, this approach works 15% of the time"
- "Here are 3 alternative approaches with higher success rates"
- "Recent wins used this type of evidence"
- "This carrier responds better to this presentation style"

### **Learning System NEVER Says:**
- "Skip this strategy"
- "Don't fight for this"  
- "This won't work"
- "Avoid this approach"

### **Team Always Decides:**
- Whether to fight for a strategy
- Which approach/evidence to use
- When to escalate vs accept
- How much time to invest in each angle

---

**The learning system is a CONSULTANT providing intelligence, not a MANAGER making decisions.**