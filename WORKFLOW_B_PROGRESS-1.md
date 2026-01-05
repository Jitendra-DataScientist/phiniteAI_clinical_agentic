# WORKFLOW B: n8n Multi-Agent Build Guide

**Created:** 2025-12-25
**Workflow Type:** Full Robust Multi-Agent System
**Current Status:** Router Agent Working ✅

---

## TABLE OF CONTENTS
1. [Completed Components](#completed-components)
2. [Architecture Overview](#architecture-overview)
3. [Current Workflow State](#current-workflow-state)
4. [Next Steps: Complete Build Instructions](#next-steps)
5. [Node Configuration Details](#node-configurations)
6. [Testing & Validation](#testing)

---

## COMPLETED COMPONENTS ✅

### Phase 1: Database Setup
- ✅ PostgreSQL database `clinical_supply_chain` created
- ✅ 40 tables loaded with data
- ✅ `table_metadata` catalog created
- ✅ `table_value_index` for fuzzy matching (236 values)
- ✅ `chat_sessions` table for conversation history
- ✅ pg_trgm extension enabled

### Phase 2: n8n Workflow (Partial)
- ✅ n8n Docker container running (v2.1.4)
- ✅ Webhook node configured (POST /clinical-chat)
- ✅ PostgreSQL node: Load session history
- ✅ HTTP Request node: Router Agent (OpenAI API)
- ✅ Code node: Parse Router Response
- ✅ IF node: Intent routing (shelf_life_extension vs general_query vs clarification)

**Workflow URL:** http://localhost:5678
**Test Webhook:** http://localhost:5678/webhook-test/clinical-chat

---

## ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEBHOOK (POST)                          │
│                 Receives: {session_id, message}                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LOAD SESSION HISTORY                         │
│           PostgreSQL: SELECT FROM chat_sessions                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ROUTER AGENT (OpenAI)                      │
│     HTTP Request → gpt-4o-mini → Returns intent + entities      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PARSE ROUTER RESPONSE                        │
│              Code Node: Extract intent & entities               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────┴────────┐
                    │   IF: INTENT?   │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    ┌────────┐         ┌──────────┐      ┌──────────────┐
    │ SHELF- │         │ GENERAL  │      │CLARIFICATION │
    │  LIFE  │         │  QUERY   │      │   NEEDED     │
    │EXTENSION│        │          │      │              │
    └────┬───┘         └────┬─────┘      └──────┬───────┘
         │                  │                    │
         │                  │                    │
    [3 AGENTS]         [SQL GEN]          [FUZZY MATCH]
         │                  │                    │
         └──────────────────┼────────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │    RESPONSE      │
                  │  SYNTHESIZER     │
                  │   (OpenAI)       │
                  └─────────┬────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │  SAVE SESSION    │
                  │   (PostgreSQL)   │
                  └─────────┬────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │ RESPOND TO       │
                  │    WEBHOOK       │
                  └──────────────────┘
```

---

## CURRENT WORKFLOW STATE

### Nodes Built So Far:

1. **Webhook** - ✅ Working
   - Path: `clinical-chat`
   - Method: POST
   - Authentication: None

2. **PostgreSQL: Load Session** - ✅ Working
   - Query: `SELECT conversation_history FROM chat_sessions WHERE session_id = '{{ $json.body.session_id }}'`
   - Options: Always Output Data = ON

3. **HTTP Request: Router Agent** - ✅ Working
   - URL: `https://api.openai.com/v1/chat/completions`
   - Method: POST
   - Headers: Authorization, Content-Type
   - Body: Router prompt with messages

4. **Code: Parse Router** - ✅ Working
   - Extracts: intent, confidence, entities, reasoning
   - Combines with webhook data

5. **IF: Route Intent** - ✅ Working
   - Condition 1: intent = shelf_life_extension → TRUE branch
   - Condition 2: intent = general_query → FALSE → Next IF
   - Condition 3: intent = clarification_needed → FALSE → Next IF

---

## NEXT STEPS: COMPLETE BUILD INSTRUCTIONS

### BRANCH 1: SHELF-LIFE EXTENSION PATH

This branch handles queries like: *"Can we extend batch LOT-45953393?"*

#### Node 1.1: Entity Validation (Code Node)

**Name:** Validate Shelf-Life Entities
**Connect from:** IF node (TRUE output for shelf_life_extension)

**Code:**
```javascript
// Check if all required entities are present
const entities = $json.entities || {};
const required = ['batch_lot', 'trial', 'country'];
const missing = [];

required.forEach(field => {
    if (!entities[field] || entities[field] === null || entities[field] === '') {
        missing.push(field);
    }
});

if (missing.length > 0) {
    // Redirect to clarification
    return [{
        json: {
            intent: 'clarification_needed',
            missing_fields: missing,
            response: `To check shelf-life extension feasibility, I need the following information: ${missing.join(', ')}. Please provide these details.`,
            skip_agents: true
        }
    }];
}

// All entities present, proceed
return [{
    json: {
        ...($json),
        proceed_to_agents: true
    }
}];
```

---

#### Node 1.2: Get Table Schemas (PostgreSQL)

**Name:** Get Schemas for Re-Eval, RIM, Logistics
**Connect from:** Entity Validation (if proceed_to_agents = true)

**Query:**
```sql
-- Get schemas for 3 key tables
SELECT
    table_name,
    column_name,
    data_type,
    ordinal_position
FROM information_schema.columns
WHERE table_name IN ('re_evaluation', 'rim', 'ip_shipping_timelines_report', 'batch_master')
  AND table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

**Options:**
- Always Output Data: ON

---

#### Node 1.3a: RE-EVALUATION CHECKER AGENT (HTTP Request)

**Name:** Agent: Re-Evaluation Checker
**Connect from:** Get Schemas node

**Method:** POST
**URL:** `https://api.openai.com/v1/chat/completions`

**Headers:**
- `Authorization`: `Bearer YOUR_API_KEY`
- `Content-Type`: `application/json`

**Body (JSON):**
```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are a re-evaluation specialist for clinical trial batches. Your job is to check if a batch has been previously re-evaluated for shelf-life extension.\n\nTABLE SCHEMA:\n{{ $json.schemas }}\n\nUSER QUERY: {{ $json.user_message }}\nBATCH NUMBER: {{ $json.entities.batch_lot }}\n\nTASK:\nGenerate a SQL query to check re-evaluation history for this batch.\n\nRESPOND IN JSON:\n{\n  \"sql_query\": \"SELECT ... FROM re_evaluation WHERE ...\",\n  \"explanation\": \"This query checks...\"\n}\n\nSQL TEMPLATE:\nSELECT \"ID\", \"Created\", \"Request Type (Molecule Planner to Complete)\", \"Sample Status (NDP Material Coordinator to Complete)\", \"Lot Number (Molecule Planner to Complete)\", \"LY Number (Molecule Planner to Complete)\", \"Target Date for Results (Molecule Planner to Complete)\", \"Modified Date\" FROM re_evaluation WHERE \"Lot Number (Molecule Planner to Complete)\" ILIKE '%{{ $json.entities.batch_lot }}%' ORDER BY \"Created\" DESC;"
    }
  ],
  "temperature": 0.2,
  "response_format": {"type": "json_object"}
}
```

---

#### Node 1.3b: Execute Re-Eval SQL (PostgreSQL)

**Name:** Execute: Re-Evaluation Query
**Connect from:** Re-Evaluation Checker Agent

**Query:**
```sql
{{ $json.choices[0].message.content.sql_query }}
```

**Options:**
- Always Output Data: ON
- Continue on Fail: OFF

---

#### Node 1.3c: Parse Re-Eval Results (Code Node)

**Name:** Parse Re-Eval Findings
**Connect from:** Execute Re-Eval SQL

**Code:**
```javascript
const results = $input.first().json;

// Analyze results
const hasBeenReevaluated = results.length > 0;
const latestRequest = results[0] || null;

let recommendation = 'No previous extension request found';
let reasoning = 'No records found in re_evaluation table for this batch.';

if (hasBeenReevaluated) {
    const requestType = latestRequest['Request Type (Molecule Planner to Complete)'];
    const status = latestRequest['Sample Status (NDP Material Coordinator to Complete)'];

    if (requestType === 'Extension' && status === 'Pending') {
        recommendation = 'Previously requested - check status';
        reasoning = `According to re_evaluation table, record ID ${latestRequest.ID} shows this batch was previously submitted for extension on ${latestRequest.Created} with status '${status}'.`;
    } else if (requestType === 'Extension' && status === 'Complete') {
        recommendation = 'Previously extended';
        reasoning = `Batch was successfully extended on ${latestRequest['Modified Date']}.`;
    }
}

return [{
    json: {
        agent: 're_evaluation_checker',
        has_been_reevaluated: hasBeenReevaluated,
        reevaluation_count: results.length,
        latest_request: latestRequest,
        recommendation: recommendation,
        reasoning: reasoning,
        citations: results.map(r => ({
            table: 're_evaluation',
            row_id: r.ID,
            data: r
        }))
    }
}];
```

---

#### Node 1.4a: REGULATORY COMPLIANCE AGENT (HTTP Request)

**Name:** Agent: Regulatory Compliance
**Connect from:** Get Schemas node (parallel to Re-Eval)

**Method:** POST
**URL:** `https://api.openai.com/v1/chat/completions`

**Body (JSON):**
```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are a regulatory compliance specialist. Check if shelf-life extension has regulatory approval in {{ $json.entities.country }}.\n\nCOUNTRY: {{ $json.entities.country }}\nTRIAL: {{ $json.entities.trial }}\n\nGenerate SQL to check RIM table for regulatory submissions.\n\nQUERY TEMPLATE:\nSELECT name_v, health_authority_division_c, type_v, status_v, approved_date_c, clinical_study_v, ly_number_c, submission_outcome FROM rim WHERE clinical_study_v ILIKE '%{{ $json.entities.trial }}%' AND health_authority_division_c ILIKE '%{{ $json.entities.country }}%' ORDER BY approved_date_c DESC;\n\nRESPOND IN JSON:\n{\n  \"sql_query\": \"...\",\n  \"explanation\": \"...\"\n}"
    }
  ],
  "temperature": 0.2,
  "response_format": {"type": "json_object"}
}
```

---

#### Node 1.4b: Execute Regulatory SQL (PostgreSQL)

**Name:** Execute: Regulatory Query
**Connect from:** Regulatory Compliance Agent

**Query:**
```sql
{{ $json.choices[0].message.content.sql_query }}
```

---

#### Node 1.4c: Parse Regulatory Results (Code Node)

**Name:** Parse Regulatory Findings
**Connect from:** Execute Regulatory SQL

**Code:**
```javascript
const results = $input.first().json;

const regulatoryApprovalExists = results.length > 0;
let recommendation = 'No regulatory submission found';
let reasoning = 'No matching records in RIM table.';

if (regulatoryApprovalExists) {
    const latest = results[0];
    const status = latest.status_v || 'Unknown';
    const outcome = latest.submission_outcome || 'Unknown';

    recommendation = status === 'Approved' ? 'Approved' : status;
    reasoning = `According to RIM table, submission '${latest.name_v}' to ${latest.health_authority_division_c} was ${status} on ${latest.approved_date_c} with outcome '${outcome}'.`;
}

return [{
    json: {
        agent: 'regulatory_compliance',
        regulatory_approval_exists: regulatoryApprovalExists,
        recommendation: recommendation,
        reasoning: reasoning,
        citations: results.map(r => ({
            table: 'rim',
            submission_name: r.name_v,
            data: r
        }))
    }
}];
```

---

#### Node 1.5a: LOGISTICS VALIDATOR AGENT (HTTP Request)

**Name:** Agent: Logistics Validator
**Connect from:** Get Schemas node (parallel to Re-Eval and Regulatory)

**Body (JSON):**
```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are a logistics specialist. Determine if there's sufficient time to execute shelf-life extension.\n\nBATCH: {{ $json.entities.batch_lot }}\nCOUNTRY: {{ $json.entities.country }}\n\nGenerate 2 SQL queries:\n1. Get batch expiry date from batch_master\n2. Get shipping timeline from ip_shipping_timelines_report\n\nQUERY 1:\nSELECT \"Batch number\", \"Expiration date_shelf life\", \"Expiry Extension Date\", \"Trial Alias\" FROM batch_master WHERE \"Batch number\" = '{{ $json.entities.batch_lot }}%';\n\nQUERY 2:\nSELECT ip_helper, ip_timeline, country_name FROM ip_shipping_timelines_report WHERE country_name ILIKE '%{{ $json.entities.country }}%';\n\nRESPOND IN JSON:\n{\n  \"sql_queries\": [\"query1\", \"query2\"],\n  \"explanation\": \"...\"\n}"
    }
  ],
  "temperature": 0.2,
  "response_format": {"type": "json_object"}
}
```

---

#### Node 1.5b-c: Execute Logistics Queries (2 PostgreSQL nodes)

Similar pattern to previous agents - execute queries and parse results.

---

#### Node 1.6: MERGE AGENT FINDINGS (Code Node)

**Name:** Merge All Agent Results
**Connect from:** All 3 Parse nodes (Re-Eval, Regulatory, Logistics)

**Code:**
```javascript
// Get all agent outputs
const allInputs = $input.all();

const agentFindings = {
    re_evaluation: null,
    regulatory: null,
    logistics: null
};

// Collect findings from each agent
allInputs.forEach(input => {
    const agent = input.json.agent;
    if (agent) {
        agentFindings[agent] = input.json;
    }
});

return [{
    json: {
        agent_findings: agentFindings,
        all_citations: [
            ...(agentFindings.re_evaluation?.citations || []),
            ...(agentFindings.regulatory?.citations || []),
            ...(agentFindings.logistics?.citations || [])
        ],
        original_query: $('Webhook').first().json.body.message,
        session_id: $('Webhook').first().json.body.session_id,
        intent: 'shelf_life_extension'
    }
}];
```

---

### BRANCH 2: GENERAL QUERY PATH

This branch handles queries like: *"Show me batches expiring in 30 days"*

#### Node 2.1: Get Relevant Schemas (PostgreSQL)

**Name:** Get Schemas for SQL Gen
**Connect from:** IF node (second condition, general_query)

**Query:**
```sql
SELECT
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = ANY(ARRAY[{{ $json.relevant_tables }}])
  AND table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

---

#### Node 2.2: SQL Generator Agent (HTTP Request)

**Name:** Agent: SQL Generator
**Connect from:** Get Schemas

**Body (JSON):**
```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are an expert PostgreSQL query generator for a clinical supply chain database.\n\nTABLE SCHEMAS:\n{{ $json.schemas }}\n\nUSER QUERY: {{ $json.user_message }}\n\nRULES:\n1. Use EXACT column names with double quotes\n2. Use ILIKE for text search\n3. Limit to 100 rows\n4. Use proper date casting\n\nEXAMPLE:\nUser: \"Show batches expiring in 30 days\"\nSQL: SELECT \"Batch number\", \"Trial Alias\", \"Expiration date_shelf life\" FROM batch_master WHERE TO_DATE(\"Expiration date_shelf life\", 'YYYY-MM-DD') BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days' ORDER BY \"Expiration date_shelf life\" LIMIT 100;\n\nRESPOND WITH ONLY THE SQL QUERY (no JSON, no explanations):"
    },
    {
      "role": "user",
      "content": "{{ $json.user_message }}"
    }
  ],
  "temperature": 0.2
}
```

---

#### Node 2.3: Execute SQL (PostgreSQL)

**Name:** Execute Generated SQL
**Connect from:** SQL Generator

**Query:**
```sql
{{ $json.choices[0].message.content }}
```

**Options:**
- Continue on Fail: ON (to handle errors)

---

#### Node 2.4: Check for SQL Errors (IF Node)

**Name:** SQL Success or Error?
**Connect from:** Execute SQL

**Condition:**
- `{{ $json.error }}` is empty → TRUE (success)
- Has error → FALSE (retry)

---

#### Node 2.5: SQL Retry Handler (Code Node)

**Name:** Prepare SQL Retry
**Connect from:** IF node (FALSE = error path)

**Code:**
```javascript
const error = $json.error || 'Unknown error';
const previousSQL = $('Agent: SQL Generator').first().json.choices[0].message.content;
const attempt = $json.retry_attempt || 1;

if (attempt >= 3) {
    return [{
        json: {
            response: `I apologize, but I couldn't generate a valid query after 3 attempts. Error: ${error}. Please rephrase your question.`,
            error: true
        }
    }];
}

// Extract error hints
let hints = [];
if (error.includes('column') && error.includes('does not exist')) {
    hints.push('Column name is incorrect. Check spelling and use double quotes.');
}
if (error.includes('syntax error')) {
    hints.push('SQL syntax error. Check quotes, commas, and structure.');
}

return [{
    json: {
        retry: true,
        retry_attempt: attempt + 1,
        previous_sql: previousSQL,
        error_message: error,
        error_hints: hints.join(' '),
        original_query: $json.user_message
    }
}];
```

**Connect:** Loop back to SQL Generator with retry context

---

#### Node 2.6: Format SQL Results (Code Node)

**Name:** Format Query Results
**Connect from:** IF node (TRUE = success path)

**Code:**
```javascript
const results = $json;
const rowCount = Array.isArray(results) ? results.length : 0;
const sql = $('Agent: SQL Generator').first().json.choices[0].message.content;

let markdown = `## Query Results\n\n`;
markdown += `**Query executed:** \`\`\`sql\n${sql}\n\`\`\`\n\n`;
markdown += `**Rows returned:** ${rowCount}\n\n`;

if (rowCount === 0) {
    markdown += `No results found.\n`;
} else {
    // Create markdown table
    const columns = Object.keys(results[0]);
    markdown += `| ${columns.join(' | ')} |\n`;
    markdown += `| ${columns.map(() => '---').join(' | ')} |\n`;

    const displayLimit = Math.min(rowCount, 50);
    for (let i = 0; i < displayLimit; i++) {
        const row = results[i];
        markdown += `| ${columns.map(col => row[col] || 'NULL').join(' | ')} |\n`;
    }

    if (rowCount > 50) {
        markdown += `\n*Showing first 50 of ${rowCount} results*\n`;
    }
}

return [{
    json: {
        response: markdown,
        results_count: rowCount,
        sql_executed: sql,
        intent: 'general_query'
    }
}];
```

---

### BRANCH 3: CLARIFICATION PATH

#### Node 3.1: Fuzzy Match Handler (Code + PostgreSQL)

**Name:** Fuzzy Match Entity
**Connect from:** IF node (third condition, clarification_needed)

**Code:**
```javascript
const ambiguous = $json.ambiguous_entities || {};
const entityType = Object.keys(ambiguous)[0];
const userInput = ambiguous[entityType];

// Map to table_value_index categories
const categoryMap = {
    'trial_alias': 'trial_alias',
    'batch_number': 'batch_number',
    'country': 'country'
};

const category = categoryMap[entityType];

if (!category) {
    return [{
        json: {
            response: `I need more information about: ${entityType}`,
            needs_clarification: true
        }
    }];
}

// Will query table_value_index for fuzzy matches
return [{
    json: {
        search_category: category,
        search_value: userInput,
        entity_type: entityType
    }
}];
```

**Follow with PostgreSQL node:**

**Query:**
```sql
SELECT
    value,
    category,
    similarity(value, '{{ $json.search_value }}') as score
FROM table_value_index
WHERE category = '{{ $json.search_category }}'
  AND similarity(value, '{{ $json.search_value }}') > 0.3
ORDER BY score DESC
LIMIT 5;
```

---

### FINAL NODES (ALL BRANCHES CONVERGE)

#### Node FINAL-1: Response Synthesizer (HTTP Request)

**Name:** Response Synthesizer
**Connect from:** All 3 branches (Merge Findings, Format Results, Fuzzy Match)

**Body (JSON):**
```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are a clinical supply chain assistant synthesizing responses.\n\nUSER QUERY: {{ $json.original_query || $json.user_message }}\n\nINTENT: {{ $json.intent }}\n\nDATA GATHERED:\n{{ JSON.stringify($json) }}\n\nTASK:\nGenerate a clear, professional markdown response that:\n1. Directly answers the user's question\n2. Cites specific data points (table names, IDs, dates)\n3. Provides recommendations if applicable\n4. Is formatted in markdown\n\nIf this is a shelf-life extension query, structure as:\n## Shelf-Life Extension Feasibility\n\n### Re-Evaluation Status\n[findings]\n\n### Regulatory Status\n[findings]\n\n### Logistics Timeline\n[findings]\n\n### Recommendation\n[final verdict]\n\nRESPOND WITH ONLY THE MARKDOWN TEXT (no JSON):"
    }
  ],
  "temperature": 0.3
}
```

---

#### Node FINAL-2: Save Session (PostgreSQL)

**Name:** Save Conversation
**Connect from:** Response Synthesizer

**Query:**
```sql
INSERT INTO chat_sessions (session_id, conversation_history, user_context, last_activity, total_messages)
VALUES (
    '{{ $json.session_id }}'::uuid,
    '[{"role": "user", "content": "{{ $json.original_query }}"}, {"role": "assistant", "content": "{{ $json.response }}"}]'::jsonb,
    '{}'::jsonb,
    NOW(),
    1
)
ON CONFLICT (session_id) DO UPDATE SET
    conversation_history = chat_sessions.conversation_history || '[{"role": "user", "content": "{{ $json.original_query }}"}, {"role": "assistant", "content": "{{ $json.response }}"}]'::jsonb,
    last_activity = NOW(),
    total_messages = chat_sessions.total_messages + 1;
```

---

#### Node FINAL-3: Respond to Webhook

**Name:** Return Response
**Connect from:** Save Conversation

**Response Body:**
```json
{
  "session_id": "={{ $json.session_id }}",
  "response": "={{ $json.response }}",
  "intent": "={{ $json.intent }}",
  "timestamp": "={{ $now }}"
}
```

---

## TESTING & VALIDATION

### Test Case 1: Shelf-Life Extension
```powershell
Invoke-RestMethod -Uri "http://localhost:5678/webhook-test/clinical-chat" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"session_id": "test-001", "message": "Can we extend batch LOT-45953393 for Trial ABC in Germany?"}'
```

**Expected:** Response with re-evaluation, regulatory, and logistics findings.

---

### Test Case 2: General Query
```powershell
Invoke-RestMethod -Uri "http://localhost:5678/webhook-test/clinical-chat" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"session_id": "test-002", "message": "Show me all batches expiring in the next 30 days"}'
```

**Expected:** SQL query results formatted as markdown table.

---

### Test Case 3: Clarification Needed
```powershell
Invoke-RestMethod -Uri "http://localhost:5678/webhook-test/clinical-chat" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"session_id": "test-003", "message": "What is the status of Trial ABC?"}'
```

**Expected:** Fuzzy match results or request for more details.

---

## BUILD PROGRESS TRACKER

### Completed Nodes:
- [x] Webhook
- [x] Load Session History
- [x] Router Agent (HTTP)
- [x] Parse Router
- [x] IF: Route Intent

### To Build - Shelf-Life Path:
- [ ] Entity Validation (Code)
- [ ] Get Schemas (PostgreSQL)
- [ ] Re-Evaluation Checker Agent (HTTP)
- [ ] Execute Re-Eval SQL (PostgreSQL)
- [ ] Parse Re-Eval Results (Code)
- [ ] Regulatory Compliance Agent (HTTP)
- [ ] Execute Regulatory SQL (PostgreSQL)
- [ ] Parse Regulatory Results (Code)
- [ ] Logistics Validator Agent (HTTP)
- [ ] Execute Logistics SQL (PostgreSQL)
- [ ] Parse Logistics Results (Code)
- [ ] Merge Agent Findings (Code)

### To Build - General Query Path:
- [ ] Get Schemas for SQL Gen (PostgreSQL)
- [ ] SQL Generator Agent (HTTP)
- [ ] Execute SQL (PostgreSQL)
- [ ] IF: SQL Success/Error
- [ ] SQL Retry Handler (Code)
- [ ] Format Results (Code)

### To Build - Clarification Path:
- [ ] Fuzzy Match Handler (Code)
- [ ] Fuzzy Match Query (PostgreSQL)

### To Build - Final Nodes:
- [ ] Response Synthesizer (HTTP)
- [ ] Save Session (PostgreSQL)
- [ ] Respond to Webhook

---

## NOTES & TIPS

### Using HTTP Request for OpenAI:
- Always use `response_format: {"type": "json_object"}` when you need JSON
- Temperature 0.2 for factual tasks, 0.3 for synthesis
- Model: `gpt-4o-mini` (cost-effective, fast)

### PostgreSQL Connection:
- Host: `host.docker.internal` (from n8n Docker)
- Database: `clinical_supply_chain`
- User: `postgres`
- Password: `SUBzero@156`

### Common Issues:
1. **Column names:** Always use double quotes, preserve exact case
2. **Parallel execution:** Use Split in Batches or ensure merge nodes wait for all inputs
3. **Error handling:** Use "Continue on Fail" + IF nodes for retry logic

---

## NEXT IMMEDIATE ACTION

**Start building the Shelf-Life Extension path:**

1. Add "Code" node after the first IF (TRUE branch)
2. Name it "Validate Shelf-Life Entities"
3. Paste the Entity Validation code
4. Connect and test

Then continue sequentially through each node in the shelf-life path.

---

**Document Version:** 1.0
**Last Updated:** 2025-12-25 02:00 UTC
