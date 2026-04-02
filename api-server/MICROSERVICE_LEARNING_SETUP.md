# Microservice Learning Setup
**Complete learning system in YOUR microservice - no Rails changes needed**

## 🎯 **Architecture**

```
Rails AiTool → HTTP → YOUR Flask API → Learning System (SQLite + JSON)
                                    ↓
                              Python Pipeline → Enhanced with learned patterns
```

**What you control 100%:**
- All learning logic
- All memory storage  
- All pattern discovery
- All API endpoints

**Rails just sends HTTP requests** - no database changes, no complex integrations.

---

## 🚀 **Setup Steps**

### **1. Initialize Learning System**
```bash
cd /Users/IFCSUP/.openclaw/workspace/tools/api-server

# Learning service is already created
python3 learning_service.py  # Test database creation
```

### **2. Start Enhanced API**
```bash
.venv/bin/python app.py
# Server starts on localhost:8090 with learning enabled
```

### **3. Test Learning Flow**
```bash
# Generate supplement (creates learning event)
curl -X POST http://localhost:8090/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Rose Brock",
    "project_id": 5128,
    "context": {"carrier": "Allstate"}
  }'

# Response includes event_id for tracking:
# {"success": true, "event_id": 1, "strategies_used": ["steep_on_waste"]}
```

### **4. Track Insurance Response**
```bash
# When insurance responds, log the outcome
curl -X POST http://localhost:8090/v1/track_response \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": 1,
    "approved_items": [{"strategy": "fence_scope", "amount": 5000}],
    "denied_items": [{"strategy": "steep_on_waste", "reason": "not covered"}]
  }'
```

### **5. Get Learning Insights**
```bash
# View learned patterns
curl "http://localhost:8090/v1/insights?carrier=Allstate&days=30"

# Response shows success rates, top strategies, recommendations
```

---

## 📊 **Data Storage**

### **Your Microservice Directory:**
```
/workspace/tools/api-server/
├── app.py                    # Enhanced Flask API
├── learning_service.py       # Learning engine
├── data/                     # All learning data
│   ├── learning.db          # SQLite database
│   ├── cache/               # Fast pattern access
│   │   ├── allstate_insights.json
│   │   └── statefarm_insights.json
│   └── logs/                # Event stream
│       ├── 2026-03-09.jsonl
│       └── 2026-03-10.jsonl
└── .venv/                   # Python dependencies
```

### **Database Tables (SQLite):**
- **supplement_events** - Every generation/response/outcome
- **learning_patterns** - Discovered carrier behaviors, strategy success
- **strategy_outcomes** - Links strategies to approval/denial results

---

## 🧠 **How Learning Works**

### **1. Pattern Discovery**
```python
# Automatic pattern detection
patterns = {
    "Allstate_behavior": {
        "denial_rate": 73.2,
        "recommendation": "conservative"
    },
    "Allstate_steep_on_waste": {
        "success_rate": 15.8,
        "recommendation": "avoid"
    }
}
```

### **2. Smart Strategy Selection**
```python
# Before supplement generation
if patterns.get("Allstate_steep_on_waste", {}).get("recommendation") == "avoid":
    # Skip steep on waste for Allstate
    strategies.remove("steep_on_waste")
    print("Learning: Skipping steep_on_waste for Allstate (15% success rate)")
```

### **3. Continuous Improvement**
```python
# After each insurance response
learning_service.track_insurance_response(event_id, approved, denied)
# → Updates success rates
# → Refines recommendations  
# → Improves next supplement
```

---

## 🔄 **Learning Flow Example**

### **Initial Supplement (No Learning)**
```
1. Team: "Generate supplement for Allstate project"
2. API: Uses standard strategies [steep_on_waste, fence_scope, O&P]
3. Result: $32K requested
4. Learning: Tracks event_id=1, strategies used
```

### **Insurance Response (Learning Input)**
```
1. Team: "Insurance denied steep, approved fence"  
2. API: Track response for event_id=1
3. Learning: steep_on_waste → denied (Allstate)
4. Pattern: Allstate steep success rate drops to 15%
```

### **Next Supplement (Applied Learning)**
```
1. Team: "Generate supplement for another Allstate project"
2. API: Sees Allstate + steep_on_waste = 15% success rate
3. Smart: Skips steep, focuses on fence_scope (80% success rate)  
4. Result: Higher approval rate, less time wasted
```

---

## 🎛️ **API Endpoints**

### **Enhanced Generation**
`POST /v1/estimate`
```json
{
  "project_name": "Rose Brock",
  "project_id": 5128,
  "context": {"carrier": "Allstate"}
}
```
**Returns:** PDF + event_id + applied learnings

### **Response Tracking**
`POST /v1/track_response`
```json
{
  "event_id": 1,
  "approved_items": [{"strategy": "fence", "amount": 5000}],
  "denied_items": [{"strategy": "steep", "reason": "not covered"}]
}
```

### **Learning Insights**
`GET /v1/insights?carrier=Allstate&days=30`
**Returns:** Success rates, top strategies, recommendations

---

## 🎯 **Integration with Rails**

### **Rails Side (Minimal):**
```ruby
# Your existing AiTool just needs to track responses
class GenerateSupplementTool
  def self.execute(tool_input, user: nil, project_id: nil)
    # 1. Call your API (already working)
    response = conn.post('/v1/estimate', body: {...})
    
    # 2. Store event_id for later response tracking
    if response.body['event_id']
      # Store in Rails session or project notes for later
      project.update(last_supplement_event_id: response.body['event_id'])
    end
    
    return response.body
  end
end

# NEW: Add response tracking tool
class TrackSupplementResponseTool
  def self.execute(tool_input, user: nil, project_id: nil)
    event_id = project.last_supplement_event_id
    
    # Call your learning API
    conn.post('/v1/track_response', body: {
      event_id: event_id,
      approved_items: tool_input['approved_items'],
      denied_items: tool_input['denied_items']
    })
  end
end
```

### **Team Usage:**
```
1. Generate supplement: "Generate supplement for this project"
   → API creates supplement + tracks event
   
2. Insurance responds: "Track response: fence approved $5K, steep denied"
   → API learns: fence works, steep doesn't
   
3. Next project: "Generate supplement"  
   → API applies learning: skips steep, focuses on fence
```

---

## 📈 **Expected Results**

### **Week 1:** Event tracking starts
### **Week 2:** First patterns discovered  
### **Week 3:** Smart strategy selection begins
### **Week 4:** Measurable approval rate improvement

**Target: 20-40% approval rate increase within 6 months**

---

## 🛠️ **Deployment**

### **Development:**
```bash
cd /workspace/tools/api-server
.venv/bin/python app.py  # Port 8090
```

### **Production:**
```bash
# Use gunicorn for production
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8090 app:app
```

### **Backup:**
```bash
# Learning data backup
cp data/learning.db backups/learning-$(date +%Y%m%d).db
tar czf learning-backup.tgz data/
```

---

**You own the entire learning system. Rails just calls your APIs. Zero complex integrations, maximum control.** 🚀