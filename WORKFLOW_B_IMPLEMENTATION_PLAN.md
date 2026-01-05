# WORKFLOW B: SCENARIO STRATEGIST - COMPLETE IMPLEMENTATION PLAN

## TABLE OF CONTENTS
1. [Overview](#overview)
2. [Architecture Design](#architecture-design)
3. [Database Setup](#database-setup)
4. [n8n Workflow Configuration](#n8n-workflow-configuration)
5. [Agent Prompts & Logic](#agent-prompts--logic)
6. [Gradio UI Implementation](#gradio-ui-implementation)
7. [Edge Case Handling](#edge-case-handling)
8. [Testing Strategy](#testing-strategy)
9. [Deployment Guide](#deployment-guide)
10. [Recommendations](#recommendations)

---

## OVERVIEW

### Business Goal
Build a conversational AI assistant that helps supply managers make complex decisions about shelf-life extensions and general supply chain data exploration.

### Key Requirements
1. **Shelf-Life Extension Logic**: Check 3 constraints (Technical, Regulatory, Logistical)
2. **Conversational Interface**: Natural language queries with context persistence
3. **Data Citation**: Explicit references to source tables and values
4. **Edge Case Handling**: Fuzzy matching, SQL self-healing, missing data gracefully handled
5. **Multi-Agent Architecture**: Clear separation of concerns

### Technology Stack
- **Orchestration**: n8n (self-hosted, free)
- **LLM**: OpenAI GPT-4o-mini
- **Database**: PostgreSQL with pg_trgm extension
- **UI**: Gradio (Python)
- **Session Management**: PostgreSQL JSONB

---

## ARCHITECTURE DESIGN

### Multi-Agent System

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                          │
│                    Gradio Chat (Port 7860)                      │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP POST
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      N8N ORCHESTRATOR                           │
│                     (Port 5678 - Webhook)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
    ┌──────────────────────┐    ┌────────────────────┐
    │  Load Session History│    │  Router Agent      │
    │  (PostgreSQL)        │───▶│  (GPT-4o-mini)     │
    └──────────────────────┘    └─────────┬──────────┘
                                          │
                        ┌─────────────────┼─────────────────┐
                        ▼                 ▼                 ▼
              ┌─────────────────┐ ┌────────────┐ ┌────────────────┐
              │ shelf_life_ext  │ │ general    │ │ clarification  │
              │                 │ │ _query     │ │ _needed        │
              └────────┬────────┘ └─────┬──────┘ └────────┬───────┘
                       │                │                  │
         ┌─────────────┼────────────┐   │                  │
         ▼             ▼            ▼   ▼                  ▼
┌────────────┐ ┌────────────┐ ┌────────────┐    ┌──────────────────┐
│Re-Eval     │ │Regulatory  │ │Logistics   │    │SQL Generator     │
│Checker     │ │Compliance  │ │Validator   │    │Agent             │
│Agent       │ │Agent       │ │Agent       │    │(GPT-4o-mini)     │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘    └────────┬─────────┘
      │              │              │                     │
      │              │              │                     ▼
      │              │              │            ┌──────────────────┐
      │              │              │            │Execute SQL       │
      │              │              │            │(PostgreSQL)      │
      │              │              │            └────────┬─────────┘
      │              │              │                     │
      │              │              │                     │ Error?
      │              │              │                     │
      │              │              │            ┌────────▼─────────┐
      │              │              │            │Retry Loop        │
      │              │              │            │(Max 3 attempts)  │
      │              │              │            └────────┬─────────┘
      └──────────────┴──────────────┴──────────────┬──────┘
                                                   │
                                                   ▼
                                        ┌────────────────────┐
                                        │Response Synthesizer│
                                        │Agent               │
                                        │(GPT-4o-mini)       │
                                        └─────────┬──────────┘
                                                  │
                                                  ▼
                                        ┌────────────────────┐
                                        │Save Conversation   │
                                        │(PostgreSQL)        │
                                        └─────────┬──────────┘
                                                  │
                                                  ▼
                                        ┌────────────────────┐
                                        │Return Response     │
                                        │to User             │
                                        └────────────────────┘
```

### Agent Responsibilities

| Agent | Tables Access | Responsibility | Output |
|-------|---------------|----------------|--------|
| **Router** | `table_metadata` (40 rows) | Classify intent, identify relevant tables | `{intent, relevant_tables[], entities}` |
| **Re-Evaluation Checker** | `re_evaluation` | Check if batch previously re-evaluated | `{has_been_reevaluated, recommendation, citations}` |
| **Regulatory Compliance** | `rim`, `material_country_requirements` | Verify regulatory approval by country | `{approval_exists, status, citations}` |
| **Logistics Validator** | `ip_shipping_timelines_report`, `batch_master` | Calculate time feasibility | `{sufficient_time, timeline_days, citations}` |
| **SQL Generator** | Dynamic (2-5 tables max) | Generate PostgreSQL queries | Valid SQL string |
| **Response Synthesizer** | None (aggregates results) | Combine findings into final answer | Markdown response with citations |

---

## DATABASE SETUP

### Schema 1: Table Metadata Catalog

**Purpose**: Lightweight index of all 40 tables for Router Agent context loading.

```sql
CREATE TABLE table_metadata (
    table_name TEXT PRIMARY KEY,
    category TEXT NOT NULL, -- 'inventory', 'demand', 'logistics', 'regulatory', 'manufacturing'
    description TEXT NOT NULL,
    key_columns TEXT[] NOT NULL, -- Array of important column names
    business_purpose TEXT NOT NULL,
    sample_row_count INTEGER,
    typical_queries TEXT[], -- Example queries this table answers
    related_tables TEXT[], -- Tables commonly joined with this one
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_metadata_category ON table_metadata(category);
CREATE INDEX idx_metadata_purpose ON table_metadata USING gin(to_tsvector('english', business_purpose));
```

**Sample Data:**
```sql
INSERT INTO table_metadata (table_name, category, description, key_columns, business_purpose, typical_queries, related_tables) VALUES
(
    're_evaluation',
    'regulatory',
    'Re-evaluation history for extending batch shelf life. Tracks requests, statuses, and outcomes.',
    ARRAY['ID', 'Lot Number (Molecule Planner to Complete)', 'Request Type (Molecule Planner to Complete)', 'Sample Status (NDP Material Coordinator to Complete)', 'LY Number (Molecule Planner to Complete)', 'Created', 'Modified Date'],
    'Check if a specific batch has been previously re-evaluated for shelf-life extension. Determine re-evaluation history and current status.',
    ARRAY['Has batch X been re-evaluated?', 'What is the re-evaluation status for LY123?', 'Show all pending re-evaluations'],
    ARRAY['batch_master', 'qdocs']
),
(
    'rim',
    'regulatory',
    'Regulatory Information Management - tracks regulatory submissions to health authorities by country.',
    ARRAY['name_v', 'health_authority_division_c', 'type_v', 'status_v', 'approved_date_c', 'clinical_study_v', 'ly_number_c', 'submission_outcome'],
    'Verify if regulatory approval exists for shelf-life extension in a specific country. Track submission status across health authorities (FDA, MHRA, EMA, etc.).',
    ARRAY['Is extension approved in Germany?', 'What is the regulatory status for LY123 in FDA?', 'Show all approved submissions for Trial ABC'],
    ARRAY['material_country_requirements']
),
(
    'ip_shipping_timelines_report',
    'logistics',
    'Shipping timelines from warehouse to sites by country. Critical for calculating lead times.',
    ARRAY['ip_helper', 'ip_timeline', 'country_name'],
    'Determine if there is sufficient time to execute shelf-life extension given shipping timelines. Calculate total lead time including re-evaluation processing.',
    ARRAY['How long does shipping to Germany take?', 'What is the timeline for country X?'],
    ARRAY['warehouse_and_site_shipment_tracking_report', 'distribution_order_report']
),
(
    'batch_master',
    'inventory',
    'Master data for all batches including expiry dates, manufacturing dates, and stock levels.',
    ARRAY['Batch number', 'Material', 'Material ID', 'Trial Alias', 'Plant', 'Expiration date_shelf life', 'Expiry Extension Date', 'Date of Manufacture', 'Total Stock', 'Unit Total Stock'],
    'Core batch information. Used to lookup batch details, current expiry status, stock levels, and trial associations.',
    ARRAY['Show details for batch X', 'What is the expiry date of batch Y?', 'List all batches for Trial ABC', 'Which batches expire in next 30 days?'],
    ARRAY['allocated_materials_to_orders', 'complete_warehouse_inventory']
),
(
    'allocated_materials_to_orders',
    'logistics',
    'Materials and batches allocated to manufacturing/packaging orders. Links batches to production.',
    ARRAY['order_id', 'material_component_batch', 'trial_alias', 'order_status', 'ly_number', 'fing_batch', 'material_description'],
    'Track which batches are allocated to which orders. Determine order status and allocation history.',
    ARRAY['Which orders use batch X?', 'Show allocations for Trial ABC', 'What batches are allocated to order 123?'],
    ARRAY['batch_master', 'manufacturing_orders']
),
(
    'material_country_requirements',
    'regulatory',
    'Material approval requirements by country. Tracks which materials are approved in which countries.',
    ARRAY['Trial Alias', 'Countries', 'Material Number', 'CT-Compound', 'Created On', 'Date of Last Change'],
    'Verify country-specific material requirements and approvals. Used in conjunction with RIM for regulatory checks.',
    ARRAY['Is material X approved in Germany?', 'Show all materials for Trial ABC in USA'],
    ARRAY['rim', 'batch_master']
);

-- Continue for all 40 tables...
```

---

### Schema 2: Value Index for Fuzzy Matching

**Purpose**: Enable fuzzy search for trial names, batch numbers, countries, LY numbers, etc.

```sql
CREATE TABLE table_value_index (
    id SERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    distinct_values TEXT[] NOT NULL, -- Sorted array of unique values
    value_count INTEGER, -- Total distinct values
    sample_size INTEGER DEFAULT 1000, -- Max values stored
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_value_index_table_column ON table_value_index(table_name, column_name);
CREATE INDEX idx_value_index_updated ON table_value_index(last_updated);

-- Unique constraint
CREATE UNIQUE INDEX idx_value_index_unique ON table_value_index(table_name, column_name);
```

**Population Script:**
```sql
-- Trial Aliases
INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
SELECT
    'batch_master',
    'Trial Alias',
    ARRAY_AGG(DISTINCT "Trial Alias" ORDER BY "Trial Alias"),
    COUNT(DISTINCT "Trial Alias")
FROM batch_master
WHERE "Trial Alias" IS NOT NULL
ON CONFLICT (table_name, column_name)
DO UPDATE SET
    distinct_values = EXCLUDED.distinct_values,
    value_count = EXCLUDED.value_count,
    last_updated = NOW();

-- Batch Numbers (sample first 1000)
INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
SELECT
    'batch_master',
    'Batch number',
    ARRAY_AGG("Batch number" ORDER BY "Batch number"),
    (SELECT COUNT(DISTINCT "Batch number") FROM batch_master)
FROM (
    SELECT DISTINCT "Batch number"
    FROM batch_master
    WHERE "Batch number" IS NOT NULL
    LIMIT 1000
) sub
ON CONFLICT (table_name, column_name)
DO UPDATE SET
    distinct_values = EXCLUDED.distinct_values,
    value_count = EXCLUDED.value_count,
    last_updated = NOW();

-- Countries
INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
SELECT
    'ip_shipping_timelines_report',
    'country_name',
    ARRAY_AGG(DISTINCT country_name ORDER BY country_name),
    COUNT(DISTINCT country_name)
FROM ip_shipping_timelines_report
WHERE country_name IS NOT NULL
ON CONFLICT (table_name, column_name)
DO UPDATE SET
    distinct_values = EXCLUDED.distinct_values,
    value_count = EXCLUDED.value_count,
    last_updated = NOW();

-- LY Numbers (sample first 1000)
INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
SELECT
    're_evaluation',
    'LY Number (Molecule Planner to Complete)',
    ARRAY_AGG(ly_num ORDER BY ly_num),
    (SELECT COUNT(DISTINCT "LY Number (Molecule Planner to Complete)") FROM re_evaluation)
FROM (
    SELECT DISTINCT "LY Number (Molecule Planner to Complete)" as ly_num
    FROM re_evaluation
    WHERE "LY Number (Molecule Planner to Complete)" IS NOT NULL
    LIMIT 1000
) sub
ON CONFLICT (table_name, column_name)
DO UPDATE SET
    distinct_values = EXCLUDED.distinct_values,
    value_count = EXCLUDED.value_count,
    last_updated = NOW();

-- Materials
INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
SELECT
    'batch_master',
    'Material',
    ARRAY_AGG(DISTINCT "Material" ORDER BY "Material"),
    COUNT(DISTINCT "Material")
FROM batch_master
WHERE "Material" IS NOT NULL
ON CONFLICT (table_name, column_name)
DO UPDATE SET
    distinct_values = EXCLUDED.distinct_values,
    value_count = EXCLUDED.value_count,
    last_updated = NOW();
```

---

### Schema 3: Chat Sessions

**Purpose**: Store conversation history and user context for each session.

```sql
CREATE TABLE chat_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP DEFAULT NOW(),
    conversation_history JSONB DEFAULT '[]'::jsonb,
    user_context JSONB DEFAULT '{}'::jsonb, -- Resolved entities (trial, batch, country, etc.)
    user_metadata JSONB DEFAULT '{}'::jsonb, -- Optional: user name, department, etc.
    total_messages INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE INDEX idx_session_activity ON chat_sessions(last_activity);
CREATE INDEX idx_session_created ON chat_sessions(created_at);
CREATE INDEX idx_session_active ON chat_sessions(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_session_context ON chat_sessions USING gin(user_context);
```

**Conversation History Format:**
```json
[
    {
        "role": "user",
        "content": "Can we extend batch LOT-45953393?",
        "timestamp": "2025-12-25T10:30:00Z",
        "entities_extracted": {
            "batch_number": "LOT-45953393"
        }
    },
    {
        "role": "assistant",
        "content": "I found batch LOT-45953393 in the system...",
        "timestamp": "2025-12-25T10:30:05Z",
        "intent": "shelf_life_extension",
        "tables_queried": ["re_evaluation", "rim", "batch_master"],
        "citations": [
            {
                "table": "re_evaluation",
                "row_id": "REV-370565",
                "finding": "Previously re-evaluated on 2025-02-26"
            }
        ]
    }
]
```

**User Context Format:**
```json
{
    "current_trial": "CT-2004-PSX",
    "current_batch": "LOT-45953393",
    "current_country": "Germany",
    "ly_number": "LY964373",
    "last_clarification": "2025-12-25T10:30:00Z"
}
```

**Cleanup Function:**
```sql
CREATE OR REPLACE FUNCTION cleanup_old_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM chat_sessions
    WHERE last_activity < NOW() - INTERVAL '24 hours'
    AND is_active = FALSE;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Schedule cleanup (manual or via cron)
-- Run daily: SELECT cleanup_old_sessions();
```

---

### Schema 4: PostgreSQL Extensions & Indexes

```sql
-- Enable fuzzy matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Trigram indexes for fuzzy search
CREATE INDEX idx_trial_alias_trgm
ON batch_master USING gin("Trial Alias" gin_trgm_ops);

CREATE INDEX idx_batch_number_trgm
ON batch_master USING gin("Batch number" gin_trgm_ops);

CREATE INDEX idx_ly_number_trgm
ON re_evaluation USING gin("LY Number (Molecule Planner to Complete)" gin_trgm_ops);

CREATE INDEX idx_country_trgm
ON ip_shipping_timelines_report USING gin(country_name gin_trgm_ops);

CREATE INDEX idx_material_trgm
ON batch_master USING gin("Material" gin_trgm_ops);

-- Full-text search indexes for descriptions
CREATE INDEX idx_batch_material_desc_fts
ON batch_master USING gin(to_tsvector('english', COALESCE("Material", '')));

CREATE INDEX idx_trial_fts
ON batch_master USING gin(to_tsvector('english', COALESCE("Trial Alias", '')));
```

**Test Fuzzy Matching:**
```sql
-- Find similar trial names
SELECT
    "Trial Alias",
    similarity("Trial Alias", 'Trial ABC') as score
FROM batch_master
WHERE "Trial Alias" % 'Trial ABC'  -- % is similarity operator
ORDER BY score DESC
LIMIT 5;

-- Find similar batch numbers
SELECT
    "Batch number",
    similarity("Batch number", 'LOT-459') as score
FROM batch_master
WHERE "Batch number" % 'LOT-459'
ORDER BY score DESC
LIMIT 5;
```

---

## N8N WORKFLOW CONFIGURATION

### n8n Installation

**Option 1: Docker (Recommended)**
```bash
# Windows
docker run -d ^
  --name n8n ^
  -p 5678:5678 ^
  -v C:\Users\cools\Downloads\clinical_agent\n8n_data:/home/node/.n8n ^
  docker.n8n.io/n8nio/n8n

# Access at: http://localhost:5678
```

**Option 2: npm**
```bash
npm install -g n8n
n8n start
```

---

### Workflow Node Structure

#### 1. Webhook Trigger
**Configuration:**
- Method: POST
- Path: `/chat`
- Response Mode: Return Immediately
- Response Data: `{{ $json }}`

**Expected Payload:**
```json
{
    "session_id": "uuid-string",
    "message": "user query",
    "history": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ],
    "timestamp": "2025-12-25T10:30:00Z"
}
```

---

#### 2. Load Session Node (PostgreSQL)
**Operation:** Execute Query
**Query:**
```sql
SELECT
    conversation_history,
    user_context,
    total_messages
FROM chat_sessions
WHERE session_id = '{{ $json.session_id }}'::uuid;
```

**If session doesn't exist, create it:**
```sql
INSERT INTO chat_sessions (session_id)
VALUES ('{{ $json.session_id }}'::uuid)
ON CONFLICT (session_id) DO NOTHING
RETURNING conversation_history, user_context, total_messages;
```

---

#### 3. Load Metadata Catalog Node (PostgreSQL)
**Operation:** Execute Query
**Query:**
```sql
SELECT
    table_name,
    category,
    description,
    key_columns,
    business_purpose,
    typical_queries
FROM table_metadata
ORDER BY category, table_name;
```

**Output Format (for Router Agent):**
```json
{
    "inventory": [
        {
            "table": "batch_master",
            "desc": "Master data for batches...",
            "key_columns": ["Batch number", "Trial Alias"],
            "purpose": "Core batch information"
        }
    ],
    "regulatory": [...],
    "logistics": [...]
}
```

---

#### 4. Router Agent Node (OpenAI)
**Model:** gpt-4o-mini
**Temperature:** 0.2
**Max Tokens:** 1500

**System Prompt:**
```
You are a routing agent for a clinical supply chain AI system. Your job is to analyze user queries and determine:
1. The user's intent
2. Which database tables are relevant
3. What entities need to be extracted or clarified

AVAILABLE TABLES (40 total, grouped by category):
{{ $json.metadata_catalog }}

CONVERSATION HISTORY (last 5 exchanges):
{{ $json.conversation_history }}

USER CONTEXT (previously resolved entities):
{{ $json.user_context }}

USER QUERY:
{{ $json.message }}

RESPOND IN VALID JSON FORMAT:
{
    "intent": "shelf_life_extension | general_query | clarification_needed",
    "confidence": 0.85,
    "relevant_tables": ["table1", "table2"],
    "extracted_entities": {
        "batch_number": "LOT-45953393",
        "trial_alias": null,
        "country": "Germany",
        "ly_number": null
    },
    "ambiguous_entities": {
        "trial_alias": "User said 'Trial ABC' but exact match not in context - needs fuzzy search"
    },
    "reasoning": "User is asking about extending batch expiry. Need to check re_evaluation, rim, and logistics tables.",
    "clarifications_needed": []
}

INTENT DEFINITIONS:
- shelf_life_extension: User asking if a batch can be extended, what's needed for extension, or extension feasibility
- general_query: User asking about inventory, shipments, enrollments, order status, etc.
- clarification_needed: Query is too ambiguous, missing critical info (batch #, trial name), or entity matching failed

RULES:
1. Use conversation history to resolve pronouns ("it", "that batch", "the trial")
2. Check user_context for previously resolved entities
3. If entity is ambiguous, mark for fuzzy matching
4. Limit relevant_tables to 2-5 tables maximum (most relevant)
5. Extract all possible entities even if not confirmed
```

**Output Parsing (Function Node):**
```javascript
// Parse Router Agent response
const routerResponse = JSON.parse($input.item.json.choices[0].message.content);

// Validate intent
const validIntents = ['shelf_life_extension', 'general_query', 'clarification_needed'];
if (!validIntents.includes(routerResponse.intent)) {
    throw new Error('Invalid intent from Router Agent');
}

return {
    json: {
        ...routerResponse,
        original_message: $json.message,
        session_id: $json.session_id
    }
};
```

---

#### 5. Switch Node (Based on Intent)

**Condition 1: shelf_life_extension**
- Route to: Shelf-Life Extension Branch

**Condition 2: general_query**
- Route to: SQL Generator Branch

**Condition 3: clarification_needed**
- Route to: Fuzzy Match Handler Branch

---

### BRANCH 1: Shelf-Life Extension Flow

#### Step 1: Entity Validation (Function Node)
```javascript
// Check if all required entities are present
const entities = $json.extracted_entities;
const required = ['batch_number', 'trial_alias', 'country'];
const missing = [];

required.forEach(field => {
    if (!entities[field] || entities[field] === null) {
        missing.push(field);
    }
});

if (missing.length > 0) {
    // Redirect to clarification
    return {
        json: {
            intent: 'clarification_needed',
            missing_fields: missing,
            message: `To check shelf-life extension feasibility, I need: ${missing.join(', ')}. Please provide these details.`
        }
    };
}

return {
    json: {
        ...entities,
        proceed: true
    }
};
```

---

#### Step 2: Get Full Schemas for Relevant Tables (PostgreSQL)
```sql
-- Get re_evaluation schema
SELECT
    column_name,
    data_type,
    (SELECT "Lot Number (Molecule Planner to Complete)" FROM re_evaluation LIMIT 1) as sample_value
FROM information_schema.columns
WHERE table_name = 're_evaluation'
ORDER BY ordinal_position;

-- Get rim schema
SELECT
    column_name,
    data_type,
    (SELECT name_v FROM rim LIMIT 1) as sample_value
FROM information_schema.columns
WHERE table_name = 'rim'
ORDER BY ordinal_position;

-- Get ip_shipping_timelines_report schema
SELECT
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'ip_shipping_timelines_report'
ORDER BY ordinal_position;
```

---

#### Step 3: Parallel Agent Execution

**Node 3A: Re-Evaluation Checker Agent (OpenAI)**

**System Prompt:**
```
You are a re-evaluation specialist for clinical trial batches. Your job is to check if a batch has been previously re-evaluated for shelf-life extension.

TABLE SCHEMA:
{{ $json.re_evaluation_schema }}

USER QUERY: {{ $json.original_message }}
BATCH NUMBER: {{ $json.batch_number }}
LY NUMBER: {{ $json.ly_number }}

TASK:
Generate a SQL query to check re-evaluation history for this batch.

SQL TEMPLATE:
SELECT
    "ID",
    "Created",
    "Request Type (Molecule Planner to Complete)",
    "Sample Status (NDP Material Coordinator to Complete)",
    "Lot Number (Molecule Planner to Complete)",
    "LY Number (Molecule Planner to Complete)",
    "Target Date for Results (Molecule Planner to Complete)",
    "Modified Date"
FROM re_evaluation
WHERE "Lot Number (Molecule Planner to Complete)" ILIKE '%{{ $json.batch_number }}%'
   OR "LY Number (Molecule Planner to Complete)" = '{{ $json.ly_number }}'
ORDER BY "Created" DESC;

Execute this query and analyze the results.

RESPOND IN JSON:
{
    "sql_query": "the SQL query you generated",
    "has_been_reevaluated": true/false,
    "reevaluation_count": 0,
    "latest_request": {
        "id": "REV-370565",
        "type": "Extension",
        "status": "Pending",
        "created_date": "2025-02-26",
        "modified_date": "2025-09-19"
    },
    "all_requests": [...],
    "recommendation": "Can proceed | Cannot proceed | More info needed",
    "reasoning": "Cite specific data: According to re_evaluation table, record ID REV-370565 shows this batch (LOT-45953393) was previously submitted for extension on 2025-02-26 with status 'Pending'. This indicates..."
}

RULES:
1. Always cite specific row IDs and dates
2. If no records found, state clearly
3. Distinguish between "Extension" vs "Retest" request types
4. Consider status: Pending, Complete, Rejected
```

**Next Node: Execute SQL (PostgreSQL)**
**Next Node: Parse Results (Function)**
```javascript
// Parse SQL results and format for Synthesizer
const results = $json.results;

return {
    json: {
        agent: 're_evaluation_checker',
        has_been_reevaluated: results.length > 0,
        reevaluation_count: results.length,
        latest_request: results[0] || null,
        all_requests: results,
        recommendation: results.length > 0 && results[0]['Request Type (Molecule Planner to Complete)'] === 'Extension'
            ? 'Previously requested - check status'
            : 'No previous extension request found',
        citations: results.map(r => ({
            table: 're_evaluation',
            row_id: r.ID,
            data: r
        }))
    }
};
```

---

**Node 3B: Regulatory Compliance Agent (OpenAI)**

**System Prompt:**
```
You are a regulatory compliance specialist. Your job is to verify if shelf-life extension has regulatory approval in a specific country.

TABLE SCHEMAS:
RIM (Regulatory Information Management):
{{ $json.rim_schema }}

MATERIAL COUNTRY REQUIREMENTS:
{{ $json.material_country_requirements_schema }}

USER QUERY: {{ $json.original_message }}
COUNTRY: {{ $json.country }}
LY NUMBER: {{ $json.ly_number }}
TRIAL: {{ $json.trial_alias }}

TASK:
Generate SQL queries to check regulatory status.

QUERY 1: Check RIM for regulatory submissions
SELECT
    name_v,
    health_authority_division_c,
    type_v,
    status_v,
    approved_date_c,
    clinical_study_v,
    ly_number_c,
    submission_outcome
FROM rim
WHERE ly_number_c = '{{ $json.ly_number }}'
  AND (
    health_authority_division_c ILIKE '%{{ $json.country }}%'
    OR clinical_study_v = '{{ $json.trial_alias }}'
  )
ORDER BY approved_date_c DESC;

QUERY 2: Check material country requirements
SELECT
    "Trial Alias",
    "Countries",
    "Material Number",
    "Created On",
    "Date of Last Change"
FROM material_country_requirements
WHERE "Trial Alias" = '{{ $json.trial_alias }}'
  AND "Countries" ILIKE '%{{ $json.country }}%';

Execute both queries and analyze results.

RESPOND IN JSON:
{
    "sql_queries": ["query1", "query2"],
    "regulatory_approval_exists": true/false,
    "rim_findings": {
        "submission_found": true/false,
        "health_authority": "MHRA",
        "status": "Approved",
        "approved_date": "2024-08-01",
        "submission_type": "Protocol Amendment",
        "outcome": "Accepted"
    },
    "material_requirements_findings": {
        "material_approved_in_country": true/false,
        "material_numbers": ["MAT-60599"],
        "last_change_date": "2024-09-15"
    },
    "recommendation": "Approved | Pending | Not submitted | Cannot determine",
    "reasoning": "According to rim table, a Protocol Amendment submission for LY964373 to MHRA (UK health authority) was approved on 2024-08-01 with outcome 'Accepted'. Additionally, material_country_requirements shows material MAT-60599 is approved for Trial CT-2004-PSX in Germany as of 2024-09-15."
}

RULES:
1. Map country names to health authorities:
   - USA → FDA
   - Germany → BfArM, EMA
   - UK → MHRA
   - France → ANSM
2. Check for submission types related to extensions: "Protocol Amendment", "Extension Request"
3. Cross-reference both tables for complete picture
4. Cite specific submission names, dates, and outcomes
```

**Next Nodes: Execute SQL 1 → Execute SQL 2 → Parse Results**

---

**Node 3C: Logistics Validator Agent (OpenAI)**

**System Prompt:**
```
You are a logistics and timeline specialist. Your job is to determine if there is sufficient time to execute a shelf-life extension.

TABLE SCHEMAS:
IP SHIPPING TIMELINES:
{{ $json.ip_shipping_timelines_schema }}

BATCH MASTER (for expiry date):
{{ $json.batch_master_schema }}

USER QUERY: {{ $json.original_message }}
COUNTRY: {{ $json.country }}
BATCH NUMBER: {{ $json.batch_number }}

TASK:
1. Get current expiry date for the batch
2. Get shipping timeline for the country
3. Calculate if there's enough time

QUERY 1: Get batch expiry date
SELECT
    "Batch number",
    "Expiration date_shelf life",
    "Expiry Extension Date",
    "Trial Alias"
FROM batch_master
WHERE "Batch number" = '{{ $json.batch_number }}';

QUERY 2: Get shipping timeline
SELECT
    ip_helper,
    ip_timeline,
    country_name
FROM ip_shipping_timelines_report
WHERE country_name ILIKE '%{{ $json.country }}%';

CALCULATION LOGIC:
- Current date: {{ $now }}
- Batch expiry: [from query 1]
- Days until expiry: [expiry - today]
- Shipping timeline: [from query 2] days
- Re-evaluation processing: 14 days (fixed buffer)
- Total required time: shipping + processing = X days
- Available time: days until expiry

RESPOND IN JSON:
{
    "sql_queries": ["query1", "query2"],
    "batch_expiry_date": "2025-12-09",
    "current_date": "2025-12-25",
    "days_until_expiry": 349,
    "shipping_timeline_days": 7,
    "processing_buffer_days": 14,
    "total_required_days": 21,
    "available_days": 349,
    "sufficient_time": true,
    "time_margin_days": 328,
    "recommendation": "Sufficient time | Tight timeline (< 30 days margin) | Insufficient time",
    "reasoning": "Based on batch_master, batch LOT-45953393 expires on 2025-12-09 (349 days from now). According to ip_shipping_timelines_report, shipping to Germany takes 7 days. Adding 14 days for re-evaluation processing, total required time is 21 days. With 349 days available, there is a comfortable margin of 328 days."
}

RULES:
1. Always calculate margins
2. Flag tight timelines (< 30 days margin) as risky
3. Consider current expiry vs extended expiry (if extension date exists)
4. Cite specific timeline values from ip_shipping_timelines_report
```

**Next Nodes: Execute SQL 1 → Execute SQL 2 → Calculate Timeline (Function) → Parse Results**

---

#### Step 4: Merge Results (Merge Node)
Combines outputs from all 3 agents:
```json
{
    "re_evaluation_result": {...},
    "regulatory_result": {...},
    "logistics_result": {...}
}
```

---

#### Step 5: Response Synthesizer Agent (OpenAI)

**System Prompt:**
```
You are the final response synthesizer for shelf-life extension queries. Your job is to combine findings from all specialist agents and provide a clear, actionable answer.

SPECIALIST FINDINGS:
RE-EVALUATION CHECKER:
{{ $json.re_evaluation_result }}

REGULATORY COMPLIANCE:
{{ $json.regulatory_result }}

LOGISTICS VALIDATOR:
{{ $json.logistics_result }}

USER QUERY:
{{ $json.original_message }}

TASK:
Synthesize a comprehensive response that:
1. Starts with a clear YES/NO/PARTIAL answer
2. Explains each of the 3 constraints (Technical, Regulatory, Logistical)
3. Cites specific data sources (table names, row IDs, values)
4. Provides actionable recommendations

FORMAT YOUR RESPONSE IN MARKDOWN:

## Can we extend the expiry of Batch #{{ $json.batch_number }} for {{ $json.trial_alias }} in {{ $json.country }}?

### Answer: **[YES / NO / PARTIAL - WITH CONDITIONS]**

---

### Detailed Analysis

#### 1. Technical Feasibility (Re-Evaluation History)
**Status:** [✓ Approved / ⚠ Pending / ✗ Blocked]

[Explain findings from re_evaluation_checker]

**Data Source:**
- Table: `re_evaluation`
- Row ID: [cite specific IDs]
- Key Data: [cite specific values]

---

#### 2. Regulatory Compliance
**Status:** [✓ Approved / ⚠ Pending / ✗ Not Approved]

[Explain findings from regulatory_compliance]

**Data Sources:**
- Table: `rim` - [cite specific submissions]
- Table: `material_country_requirements` - [cite specific approvals]

---

#### 3. Logistical Feasibility
**Status:** [✓ Sufficient Time / ⚠ Tight Timeline / ✗ Insufficient Time]

[Explain timeline calculations]

**Timeline Breakdown:**
- Current expiry: [date]
- Days remaining: [X]
- Shipping time: [Y] days
- Processing buffer: 14 days
- Total required: [Z] days
- **Margin: [M] days**

**Data Sources:**
- Table: `batch_master` - Batch #{{ $json.batch_number }}
- Table: `ip_shipping_timelines_report` - {{ $json.country }}

---

### Overall Recommendation

[Provide clear next steps based on overall assessment]

**If YES:**
- Proceed with re-evaluation request
- Expected timeline: [X] days
- Next steps: [specific actions]

**If NO:**
- Blockers: [list specific issues]
- Alternative options: [if any]

**If PARTIAL:**
- Conditions that must be met: [list]
- Risks to consider: [list]
- Recommended actions: [list]

---

### Data Citations Summary
- `re_evaluation`: [list row IDs referenced]
- `rim`: [list submissions referenced]
- `material_country_requirements`: [list records referenced]
- `batch_master`: [batch details]
- `ip_shipping_timelines_report`: [timeline details]

---

RULES:
1. Be concise but complete
2. Always cite specific data (no generalizations)
3. Use clear status indicators (✓ ⚠ ✗)
4. Provide actionable next steps
5. Highlight any risks or concerns
6. If data is missing or contradictory, state it explicitly
```

---

### BRANCH 2: General Query Flow

#### Step 1: Get Relevant Table Schemas (PostgreSQL Function)
```sql
-- Dynamic schema retrieval based on Router's relevant_tables
SELECT
    c.table_name,
    c.column_name,
    c.data_type,
    c.ordinal_position
FROM information_schema.columns c
WHERE c.table_name = ANY(ARRAY[{{ $json.relevant_tables }}])
  AND c.table_schema = 'public'
ORDER BY c.table_name, c.ordinal_position;
```

**Format for SQL Generator:**
```json
{
    "batch_master": {
        "columns": [
            {"name": "Batch number", "type": "text"},
            {"name": "Trial Alias", "type": "text"},
            {"name": "Expiration date_shelf life", "type": "text"}
        ],
        "sample_query": "SELECT * FROM batch_master WHERE \"Trial Alias\" = 'ABC' LIMIT 10;"
    }
}
```

---

#### Step 2: SQL Generator Agent (OpenAI)

**System Prompt:**
```
You are an expert PostgreSQL query generator for a clinical supply chain database.

RELEVANT TABLE SCHEMAS:
{{ $json.schemas }}

USER QUERY: {{ $json.original_message }}

CONVERSATION HISTORY:
{{ $json.conversation_history }}

EXTRACTED ENTITIES:
{{ $json.extracted_entities }}

TASK:
Generate a valid PostgreSQL query to answer the user's question.

RULES:
1. Use EXACT column names (case-sensitive, preserve spaces and special characters)
2. Always use double quotes for column names: "Trial Alias", "Batch number"
3. Use ILIKE for case-insensitive text search: WHERE "Trial Alias" ILIKE '%ABC%'
4. For date comparisons, use TO_DATE() or proper date casting
5. Limit results to 100 rows unless user specifies otherwise
6. Use proper JOINs when querying multiple tables
7. Avoid SELECT * unless explicitly requested - select only relevant columns
8. Add ORDER BY for sorted results
9. Use NULLIF and COALESCE to handle nulls gracefully

EXAMPLES:
User: "Show me batches expiring in next 30 days"
SQL:
SELECT
    "Batch number",
    "Trial Alias",
    "Material",
    "Expiration date_shelf life",
    CURRENT_DATE - TO_DATE("Expiration date_shelf life", 'YYYY-MM-DD') as days_until_expiry
FROM batch_master
WHERE TO_DATE("Expiration date_shelf life", 'YYYY-MM-DD') BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
ORDER BY "Expiration date_shelf life"
LIMIT 100;

User: "What's the inventory for Trial ABC?"
SQL:
SELECT
    trial_alias,
    warehouse_name,
    description,
    SUM(CAST(actual_qty AS NUMERIC)) as total_quantity
FROM complete_warehouse_inventory
WHERE trial_alias ILIKE '%ABC%'
GROUP BY trial_alias, warehouse_name, description
ORDER BY total_quantity DESC
LIMIT 100;

RESPOND WITH ONLY THE SQL QUERY (no explanations, no markdown):
```

**Output:** Raw SQL string

---

#### Step 3: Execute SQL (PostgreSQL Node)

**Configuration:**
- Query: `{{ $json.sql_query }}`
- Timeout: 30 seconds

**Error Handling:** Catch errors → send to Retry Loop

---

#### Step 4: SQL Retry Loop (If Error)

**Function Node: Error Analyzer**
```javascript
const error = $json.error_message;
const sql = $json.sql_query;
const attempt = $json.attempt || 1;
const maxRetries = 3;

if (attempt > maxRetries) {
    return {
        json: {
            success: false,
            error: `Failed after ${maxRetries} attempts`,
            lastError: error,
            lastSQL: sql,
            message: `I apologize, but I couldn't generate a valid query after ${maxRetries} attempts. The error was: ${error}. Please rephrase your question or be more specific about what you're looking for.`
        }
    };
}

// Prepare error context for SQL Generator
return {
    json: {
        retry: true,
        attempt: attempt + 1,
        previous_sql: sql,
        error_message: error,
        error_hints: extractErrorHints(error),
        original_query: $json.original_message
    }
};

function extractErrorHints(error) {
    const hints = [];

    if (error.includes('column') && error.includes('does not exist')) {
        hints.push('Column name is incorrect or misspelled. Check exact column names in schema.');
    }
    if (error.includes('syntax error')) {
        hints.push('SQL syntax error. Check quotes, commas, and statement structure.');
    }
    if (error.includes('invalid input syntax for type date')) {
        hints.push('Date format is incorrect. Use TO_DATE() with proper format string.');
    }
    if (error.includes('relation') && error.includes('does not exist')) {
        hints.push('Table name is incorrect. Check available tables.');
    }

    return hints;
}
```

**Retry Prompt to SQL Generator:**
```
Your previous query failed with this error:
{{ $json.error_message }}

PREVIOUS SQL:
{{ $json.previous_sql }}

ERROR HINTS:
{{ $json.error_hints }}

SCHEMAS (for reference):
{{ $json.schemas }}

Generate a CORRECTED SQL query that fixes the error.

COMMON FIXES:
- Column not found: Check spelling, case, and use double quotes
- Syntax error: Check for missing commas, unmatched quotes
- Date error: Use TO_DATE("column_name", 'YYYY-MM-DD')
- Table not found: Check table name spelling

RESPOND WITH ONLY THE CORRECTED SQL:
```

**Loop back to Execute SQL → Repeat up to 3 times**

---

#### Step 5: Format Results (Function Node)

```javascript
const results = $json.results;
const rowCount = results.length;
const sql = $json.sql_query;

// Format results as markdown table
let markdown = `## Query Results\n\n`;
markdown += `**Query executed:** \`\`\`sql\n${sql}\n\`\`\`\n\n`;
markdown += `**Rows returned:** ${rowCount}\n\n`;

if (rowCount === 0) {
    markdown += `No results found.\n`;
} else {
    // Create table header
    const columns = Object.keys(results[0]);
    markdown += `| ${columns.join(' | ')} |\n`;
    markdown += `| ${columns.map(() => '---').join(' | ')} |\n`;

    // Add rows (limit to 50 for display)
    const displayLimit = Math.min(rowCount, 50);
    for (let i = 0; i < displayLimit; i++) {
        const row = results[i];
        markdown += `| ${columns.map(col => row[col] || 'NULL').join(' | ')} |\n`;
    }

    if (rowCount > 50) {
        markdown += `\n*Showing first 50 of ${rowCount} results*\n`;
    }
}

return {
    json: {
        response: markdown,
        results_count: rowCount,
        sql_executed: sql
    }
};
```

---

### BRANCH 3: Clarification Flow

#### Step 1: Fuzzy Match Handler (Function + PostgreSQL)

```javascript
// Get ambiguous entity from Router
const ambiguous = $json.ambiguous_entities;
const entity_type = Object.keys(ambiguous)[0]; // e.g., "trial_alias"
const user_input = ambiguous[entity_type];

// Determine which table/column to search
const searchMap = {
    'trial_alias': { table: 'batch_master', column: 'Trial Alias' },
    'batch_number': { table: 'batch_master', column: 'Batch number' },
    'country': { table: 'ip_shipping_timelines_report', column: 'country_name' },
    'ly_number': { table: 're_evaluation', column: 'LY Number (Molecule Planner to Complete)' }
};

const search = searchMap[entity_type];

return {
    json: {
        entity_type: entity_type,
        user_input: user_input,
        search_table: search.table,
        search_column: search.column
    }
};
```

**Next: PostgreSQL Fuzzy Search**
```sql
-- Using pg_trgm similarity
SELECT
    "{{ $json.search_column }}" as value,
    similarity("{{ $json.search_column }}", '{{ $json.user_input }}') as score
FROM {{ $json.search_table }}
WHERE "{{ $json.search_column }}" % '{{ $json.user_input }}'  -- % = similarity operator
ORDER BY score DESC
LIMIT 5;
```

**Next: Format Clarification Response**
```javascript
const matches = $json.matches;

if (matches.length === 0) {
    return {
        json: {
            response: `I couldn't find any matches for "${$json.user_input}". Please check the spelling or try a different search term.`,
            needs_clarification: true
        }
    };
}

if (matches.length === 1) {
    // Auto-select if only one match
    return {
        json: {
            response: `I found one match: **${matches[0].value}**. Proceeding with this.`,
            resolved_entity: matches[0].value,
            auto_selected: true
        }
    };
}

// Multiple matches - ask user to clarify
let response = `I found multiple matches for "${$json.user_input}":\n\n`;
matches.forEach((match, idx) => {
    response += `${idx + 1}. ${match.value} (similarity: ${(match.score * 100).toFixed(0)}%)\n`;
});
response += `\nWhich one did you mean? Please specify by number or full name.`;

return {
    json: {
        response: response,
        needs_clarification: true,
        options: matches.map(m => m.value)
    }
};
```

---

### Final Steps (All Branches)

#### Save Conversation Node (PostgreSQL)
```sql
UPDATE chat_sessions
SET
    conversation_history = conversation_history || '{{ $json.new_message }}'::jsonb,
    user_context = '{{ $json.updated_context }}'::jsonb,
    last_activity = NOW(),
    total_messages = total_messages + 1
WHERE session_id = '{{ $json.session_id }}'::uuid;
```

#### Return Response Node
```javascript
return {
    json: {
        session_id: $json.session_id,
        response: $json.response,
        intent: $json.intent,
        tables_queried: $json.tables_queried || [],
        citations: $json.citations || [],
        timestamp: new Date().toISOString()
    }
};
```

---

## AGENT PROMPTS & LOGIC

### Complete Agent Prompt Files

Create separate files for each agent prompt:

**Files to create:**
```
agents/
├── router_agent.txt
├── re_evaluation_checker.txt
├── regulatory_compliance.txt
├── logistics_validator.txt
├── sql_generator.txt
├── sql_error_fixer.txt
└── response_synthesizer.txt
```

---

## GRADIO UI IMPLEMENTATION

### File: `gradio_chat_ui.py`

```python
"""
Gradio Chat UI for Clinical Supply Chain Assistant - Workflow B
"""
import gradio as gr
import requests
import uuid
import json
from datetime import datetime
from typing import List, Tuple, Optional

# Configuration
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/chat"
SESSION_TIMEOUT_MINUTES = 60

# Global session management
session_id = None
session_start_time = None


def initialize_session() -> str:
    """Create new session ID."""
    global session_id, session_start_time
    if session_id is None or is_session_expired():
        session_id = str(uuid.uuid4())
        session_start_time = datetime.now()
        print(f"New session created: {session_id}")
    return session_id


def is_session_expired() -> bool:
    """Check if current session has expired."""
    global session_start_time
    if session_start_time is None:
        return True
    elapsed = (datetime.now() - session_start_time).total_seconds() / 60
    return elapsed > SESSION_TIMEOUT_MINUTES


def format_history_for_n8n(history: List[Tuple[str, str]]) -> List[dict]:
    """Convert Gradio history format to n8n format."""
    formatted = []
    for user_msg, assistant_msg in history:
        formatted.append({"role": "user", "content": user_msg})
        if assistant_msg:  # Could be None during processing
            formatted.append({"role": "assistant", "content": assistant_msg})
    return formatted


def chat_with_assistant(message: str, history: List[Tuple[str, str]]) -> str:
    """
    Send message to n8n workflow and return response.

    Args:
        message: User's input message
        history: Chat history from Gradio

    Returns:
        Assistant's response
    """
    # Initialize or refresh session
    sess_id = initialize_session()

    # Format history (keep last 10 messages = 5 exchanges)
    formatted_history = format_history_for_n8n(history[-5:])

    # Prepare payload
    payload = {
        "session_id": sess_id,
        "message": message,
        "history": formatted_history,
        "timestamp": datetime.now().isoformat()
    }

    try:
        # Call n8n webhook
        print(f"Sending request to n8n: {N8N_WEBHOOK_URL}")
        print(f"Payload: {json.dumps(payload, indent=2)}")

        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            timeout=90  # Extended timeout for complex queries
        )

        print(f"Response status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            assistant_reply = result.get("response", "Error: No response from assistant")

            # Log metadata if available
            if "intent" in result:
                print(f"Intent: {result['intent']}")
            if "tables_queried" in result:
                print(f"Tables queried: {result['tables_queried']}")

        elif response.status_code == 404:
            assistant_reply = """
⚠️ **n8n webhook not found**

Please ensure:
1. n8n is running at http://localhost:5678
2. The webhook is configured with path `/chat`
3. The workflow is activated

You can start n8n with:
```bash
docker run -p 5678:5678 docker.n8n.io/n8nio/n8n
```
"""
        else:
            assistant_reply = f"❌ Error: HTTP {response.status_code}\n\n```\n{response.text}\n```"

    except requests.exceptions.Timeout:
        assistant_reply = """
⏱️ **Request timed out**

The query took too long to process. This could be because:
- The query is very complex
- n8n is processing a large dataset
- Database is slow to respond

Please try:
1. Simplifying your query
2. Being more specific about what you need
3. Waiting a moment and trying again
"""
    except requests.exceptions.ConnectionError:
        assistant_reply = """
🔌 **Connection failed**

Cannot connect to n8n at http://localhost:5678

Please ensure n8n is running:
```bash
# Using Docker
docker run -p 5678:5678 docker.n8n.io/n8nio/n8n

# Using npm
n8n start
```

Then refresh this page and try again.
"""
    except Exception as e:
        assistant_reply = f"""
❌ **Unexpected error**

```
{str(e)}
```

Please check:
1. n8n is running and accessible
2. Webhook URL is correct: {N8N_WEBHOOK_URL}
3. Network connectivity
"""

    return assistant_reply


def get_example_queries() -> List[Tuple[str, str]]:
    """Return example queries for the UI."""
    return [
        ("Shelf-Life Extension", "Can we extend the expiry of batch LOT-45953393 for trial CT-2004-PSX in Germany?"),
        ("Inventory Check", "Show me all batches expiring in the next 30 days"),
        ("Trial Inventory", "What's the current inventory for trial CT-2004-PSX?"),
        ("Shipping Timeline", "How long does shipping to Germany take?"),
        ("Batch Details", "Show me details for batch LOT-45953393"),
        ("Country Shipments", "What shipments are going to Germany?"),
        ("Re-evaluation History", "Has batch LOT-45953393 been re-evaluated before?"),
        ("Enrollment Data", "Show me enrollment data for trial CT-2004-PSX"),
    ]


# Create Gradio Interface
with gr.Blocks(
    title="Clinical Supply Chain Assistant",
    theme=gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
    ),
    css="""
        .example-box {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background: #f9f9f9;
        }
        .info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 12px;
            margin: 12px 0;
            border-radius: 4px;
        }
    """
) as demo:

    # Header
    gr.Markdown(
        """
        # 🏥 Clinical Supply Chain Assistant

        <div class="info-box">

        **Workflow B: Scenario Strategist** - Your AI assistant for supply chain decisions

        Ask questions about:
        - 🔄 Shelf-life extensions (feasibility, requirements, approvals)
        - 📦 Inventory levels and batch details
        - 🚚 Shipments and distribution
        - 📊 Enrollment and patient data
        - 🧪 Manufacturing orders and materials

        </div>
        """
    )

    # Chat Interface
    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                [],
                elem_id="chatbot",
                bubble_full_width=False,
                height=550,
                show_label=False,
                avatar_images=(
                    None,  # User avatar
                    "https://em-content.zobj.net/source/twitter/376/robot_1f916.png"  # Assistant avatar
                )
            )

            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Ask a question about supply chain...",
                    scale=5,
                    container=False,
                    lines=1,
                    max_lines=3
                )
                submit_btn = gr.Button("Send", scale=1, variant="primary")

            with gr.Row():
                clear_btn = gr.Button("🗑️ Clear Chat", size="sm")
                retry_btn = gr.Button("🔄 Retry Last", size="sm")

        # Sidebar
        with gr.Column(scale=1):
            gr.Markdown("### 💡 Example Queries")

            example_queries = get_example_queries()
            for category, query in example_queries:
                gr.Button(
                    f"{category}",
                    size="sm",
                    variant="secondary"
                ).click(
                    lambda q=query: q,
                    outputs=[msg]
                )

            gr.Markdown("---")

            session_info = gr.Textbox(
                value="Session will be created on first message",
                label="📊 Session Info",
                interactive=False,
                lines=3,
                max_lines=5
            )

            gr.Markdown(
                """
                ---
                ### ⚙️ System Status
                - **n8n**: http://localhost:5678
                - **Database**: PostgreSQL
                - **Model**: GPT-4o-mini
                """
            )

    # Event handlers
    def respond(message: str, chat_history: List[Tuple[str, str]]) -> Tuple[str, List[Tuple[str, str]]]:
        """Handle user message and update chat."""
        if not message.strip():
            return "", chat_history

        # Get assistant response
        bot_message = chat_with_assistant(message, chat_history)

        # Update history
        chat_history.append((message, bot_message))

        return "", chat_history

    def update_session_info() -> str:
        """Update session info display."""
        sess_id = initialize_session()
        elapsed = (datetime.now() - session_start_time).total_seconds() / 60

        info = f"""
**Session ID:** {sess_id[:8]}...
**Status:** Active
**Elapsed:** {elapsed:.1f} min
**Timeout:** {SESSION_TIMEOUT_MINUTES} min
        """.strip()

        return info

    def retry_last(chat_history: List[Tuple[str, str]]) -> Tuple[str, List[Tuple[str, str]]]:
        """Retry the last user message."""
        if not chat_history:
            return "", chat_history

        # Get last user message
        last_user_msg = chat_history[-1][0]

        # Remove last exchange
        chat_history = chat_history[:-1]

        # Re-send
        return respond(last_user_msg, chat_history)

    # Wire up events
    msg.submit(respond, [msg, chatbot], [msg, chatbot]).then(
        update_session_info, None, session_info
    )

    submit_btn.click(respond, [msg, chatbot], [msg, chatbot]).then(
        update_session_info, None, session_info
    )

    clear_btn.click(
        lambda: ([], "Session cleared"),
        None,
        [chatbot, session_info]
    ).then(
        lambda: None,
        None,
        None,
        _js="() => { window.location.reload(); }"  # Reload to reset session
    )

    retry_btn.click(retry_last, [chatbot], [msg, chatbot])

    # Initialize session on load
    demo.load(update_session_info, None, session_info)


if __name__ == "__main__":
    print("=" * 60)
    print("Clinical Supply Chain Assistant - Workflow B")
    print("=" * 60)
    print(f"n8n webhook: {N8N_WEBHOOK_URL}")
    print(f"Session timeout: {SESSION_TIMEOUT_MINUTES} minutes")
    print("=" * 60)

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
        inbrowser=True  # Auto-open browser
    )
```

---

### File: `setup_workflow_b.py`

```python
"""
Setup database tables and indexes for Workflow B: Scenario Strategist
"""
from sqlalchemy import create_engine, URL, text
from config import Config
import sys


def create_tables(engine):
    """Create all required tables."""
    print("\n1. Creating tables...")

    with engine.connect() as conn:
        # Table metadata catalog
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS table_metadata (
                table_name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                key_columns TEXT[] NOT NULL,
                business_purpose TEXT NOT NULL,
                typical_queries TEXT[],
                related_tables TEXT[],
                sample_row_count INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        print("   ✓ table_metadata created")

        # Value index for fuzzy matching
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS table_value_index (
                id SERIAL PRIMARY KEY,
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                distinct_values TEXT[] NOT NULL,
                value_count INTEGER,
                sample_size INTEGER DEFAULT 1000,
                last_updated TIMESTAMP DEFAULT NOW()
            )
        """))
        print("   ✓ table_value_index created")

        # Chat sessions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMP DEFAULT NOW(),
                last_activity TIMESTAMP DEFAULT NOW(),
                conversation_history JSONB DEFAULT '[]'::jsonb,
                user_context JSONB DEFAULT '{}'::jsonb,
                user_metadata JSONB DEFAULT '{}'::jsonb,
                total_messages INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))
        print("   ✓ chat_sessions created")

        conn.commit()


def create_indexes(engine):
    """Create indexes for performance."""
    print("\n2. Creating indexes...")

    with engine.connect() as conn:
        # Metadata indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_metadata_category
            ON table_metadata(category)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_metadata_purpose
            ON table_metadata USING gin(to_tsvector('english', business_purpose))
        """))

        # Value index indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_value_index_table_column
            ON table_value_index(table_name, column_name)
        """))

        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_value_index_unique
            ON table_value_index(table_name, column_name)
        """))

        # Session indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_activity
            ON chat_sessions(last_activity)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_active
            ON chat_sessions(is_active) WHERE is_active = TRUE
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_context
            ON chat_sessions USING gin(user_context)
        """))

        conn.commit()
        print("   ✓ All indexes created")


def enable_extensions(engine):
    """Enable PostgreSQL extensions."""
    print("\n3. Enabling extensions...")

    with engine.connect() as conn:
        # pg_trgm for fuzzy matching
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        print("   ✓ pg_trgm enabled")

        conn.commit()


def create_fuzzy_indexes(engine):
    """Create trigram indexes for fuzzy matching."""
    print("\n4. Creating fuzzy match indexes...")

    with engine.connect() as conn:
        # Trial alias
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_trial_alias_trgm
            ON batch_master USING gin("Trial Alias" gin_trgm_ops)
        """))

        # Batch number
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_batch_number_trgm
            ON batch_master USING gin("Batch number" gin_trgm_ops)
        """))

        # LY Number
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ly_number_trgm
            ON re_evaluation USING gin("LY Number (Molecule Planner to Complete)" gin_trgm_ops)
        """))

        # Country
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_country_trgm
            ON ip_shipping_timelines_report USING gin(country_name gin_trgm_ops)
        """))

        # Material
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_material_trgm
            ON batch_master USING gin("Material" gin_trgm_ops)
        """))

        conn.commit()
        print("   ✓ All fuzzy match indexes created")


def populate_metadata(engine):
    """Populate table_metadata with key tables."""
    print("\n5. Populating table metadata...")

    metadata_entries = [
        {
            'table': 're_evaluation',
            'category': 'regulatory',
            'description': 'Re-evaluation history for extending batch shelf life. Tracks requests, statuses, and outcomes.',
            'key_columns': ['ID', 'Lot Number (Molecule Planner to Complete)', 'Request Type (Molecule Planner to Complete)', 'Sample Status (NDP Material Coordinator to Complete)', 'LY Number (Molecule Planner to Complete)'],
            'purpose': 'Check if a specific batch has been previously re-evaluated for shelf-life extension. Determine re-evaluation history and current status.',
            'typical_queries': ['Has batch X been re-evaluated?', 'What is the re-evaluation status for LY123?', 'Show all pending re-evaluations'],
            'related_tables': ['batch_master', 'qdocs']
        },
        {
            'table': 'rim',
            'category': 'regulatory',
            'description': 'Regulatory Information Management - tracks regulatory submissions to health authorities by country.',
            'key_columns': ['name_v', 'health_authority_division_c', 'type_v', 'status_v', 'approved_date_c', 'clinical_study_v', 'ly_number_c', 'submission_outcome'],
            'purpose': 'Verify if regulatory approval exists for shelf-life extension in a specific country. Track submission status across health authorities.',
            'typical_queries': ['Is extension approved in Germany?', 'What is the regulatory status for LY123 in FDA?', 'Show all approved submissions for Trial ABC'],
            'related_tables': ['material_country_requirements']
        },
        {
            'table': 'ip_shipping_timelines_report',
            'category': 'logistics',
            'description': 'Shipping timelines from warehouse to sites by country. Critical for calculating lead times.',
            'key_columns': ['ip_helper', 'ip_timeline', 'country_name'],
            'purpose': 'Determine if there is sufficient time to execute shelf-life extension given shipping timelines. Calculate total lead time including re-evaluation processing.',
            'typical_queries': ['How long does shipping to Germany take?', 'What is the timeline for country X?'],
            'related_tables': ['warehouse_and_site_shipment_tracking_report', 'distribution_order_report']
        },
        {
            'table': 'batch_master',
            'category': 'inventory',
            'description': 'Master data for all batches including expiry dates, manufacturing dates, and stock levels.',
            'key_columns': ['Batch number', 'Material', 'Trial Alias', 'Expiration date_shelf life', 'Expiry Extension Date', 'Total Stock'],
            'purpose': 'Core batch information. Used to lookup batch details, current expiry status, stock levels, and trial associations.',
            'typical_queries': ['Show details for batch X', 'What is the expiry date of batch Y?', 'List all batches for Trial ABC'],
            'related_tables': ['allocated_materials_to_orders', 'complete_warehouse_inventory']
        },
        {
            'table': 'allocated_materials_to_orders',
            'category': 'logistics',
            'description': 'Materials and batches allocated to manufacturing/packaging orders. Links batches to production.',
            'key_columns': ['order_id', 'material_component_batch', 'trial_alias', 'order_status', 'ly_number'],
            'purpose': 'Track which batches are allocated to which orders. Determine order status and allocation history.',
            'typical_queries': ['Which orders use batch X?', 'Show allocations for Trial ABC'],
            'related_tables': ['batch_master', 'manufacturing_orders']
        },
        {
            'table': 'material_country_requirements',
            'category': 'regulatory',
            'description': 'Material approval requirements by country. Tracks which materials are approved in which countries.',
            'key_columns': ['Trial Alias', 'Countries', 'Material Number'],
            'purpose': 'Verify country-specific material requirements and approvals. Used in conjunction with RIM for regulatory checks.',
            'typical_queries': ['Is material X approved in Germany?', 'Show all materials for Trial ABC in USA'],
            'related_tables': ['rim', 'batch_master']
        },
    ]

    with engine.connect() as conn:
        for entry in metadata_entries:
            conn.execute(text("""
                INSERT INTO table_metadata (
                    table_name, category, description, key_columns,
                    business_purpose, typical_queries, related_tables
                )
                VALUES (
                    :table, :category, :description, :key_columns,
                    :purpose, :typical_queries, :related_tables
                )
                ON CONFLICT (table_name) DO UPDATE SET
                    category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    key_columns = EXCLUDED.key_columns,
                    business_purpose = EXCLUDED.business_purpose,
                    typical_queries = EXCLUDED.typical_queries,
                    related_tables = EXCLUDED.related_tables,
                    updated_at = NOW()
            """), entry)

        conn.commit()
        print(f"   ✓ Populated {len(metadata_entries)} key tables")
        print(f"   ⚠ Note: Remaining tables should be added manually or via script")


def populate_value_index(engine):
    """Populate value index for fuzzy matching."""
    print("\n6. Populating value index...")

    with engine.connect() as conn:
        # Trial aliases
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'batch_master',
                'Trial Alias',
                ARRAY_AGG(DISTINCT "Trial Alias" ORDER BY "Trial Alias"),
                COUNT(DISTINCT "Trial Alias")
            FROM batch_master
            WHERE "Trial Alias" IS NOT NULL
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} trial aliases")

        # Batch numbers (sample 1000)
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'batch_master',
                'Batch number',
                ARRAY_AGG("Batch number" ORDER BY "Batch number"),
                (SELECT COUNT(DISTINCT "Batch number") FROM batch_master)
            FROM (
                SELECT DISTINCT "Batch number"
                FROM batch_master
                WHERE "Batch number" IS NOT NULL
                LIMIT 1000
            ) sub
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} batch numbers (sample)")

        # Countries
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'ip_shipping_timelines_report',
                'country_name',
                ARRAY_AGG(DISTINCT country_name ORDER BY country_name),
                COUNT(DISTINCT country_name)
            FROM ip_shipping_timelines_report
            WHERE country_name IS NOT NULL
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} countries")

        conn.commit()


def create_cleanup_function(engine):
    """Create session cleanup function."""
    print("\n7. Creating cleanup function...")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION cleanup_old_sessions()
            RETURNS INTEGER AS $$
            DECLARE
                deleted_count INTEGER;
            BEGIN
                DELETE FROM chat_sessions
                WHERE last_activity < NOW() - INTERVAL '24 hours'
                AND is_active = FALSE;

                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                RETURN deleted_count;
            END;
            $$ LANGUAGE plpgsql;
        """))

        conn.commit()
        print("   ✓ Cleanup function created")


def test_fuzzy_matching(engine):
    """Test fuzzy matching functionality."""
    print("\n8. Testing fuzzy matching...")

    with engine.connect() as conn:
        # Test trial alias matching
        result = conn.execute(text("""
            SELECT
                "Trial Alias",
                similarity("Trial Alias", 'Trial ABC') as score
            FROM batch_master
            WHERE "Trial Alias" % 'Trial ABC'
            ORDER BY score DESC
            LIMIT 3
        """))

        matches = result.fetchall()
        if matches:
            print("   ✓ Fuzzy matching working:")
            for match in matches:
                print(f"      - {match[0]} (score: {match[1]:.2f})")
        else:
            print("   ⚠ No fuzzy matches found (this might be normal if no similar data exists)")


def main():
    """Main setup function."""
    print("=" * 60)
    print("WORKFLOW B: DATABASE SETUP")
    print("=" * 60)

    # Create engine
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        database=Config.DB_NAME,
    )

    try:
        engine = create_engine(url)

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"\n✓ Connected to PostgreSQL")
            print(f"  Version: {version.split(',')[0]}")

        # Run setup steps
        create_tables(engine)
        create_indexes(engine)
        enable_extensions(engine)
        create_fuzzy_indexes(engine)
        populate_metadata(engine)
        populate_value_index(engine)
        create_cleanup_function(engine)
        test_fuzzy_matching(engine)

        print("\n" + "=" * 60)
        print("✓ SETUP COMPLETE")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start n8n: docker run -p 5678:5678 docker.n8n.io/n8nio/n8n")
        print("2. Import n8n workflow")
        print("3. Start Gradio UI: python gradio_chat_ui.py")
        print("\n" + "=" * 60)

        engine.dispose()
        return 0

    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## EDGE CASE HANDLING

### 1. Fuzzy Matching Edge Cases

**Scenario: User says "Trial ABC" but DB has "Trial_ABC_v2", "Trial ABC 2024", "ABC-Extension"**

**Solution:**
```sql
-- Fuzzy search with similarity threshold
SELECT
    "Trial Alias",
    similarity("Trial Alias", 'Trial ABC') as score
FROM batch_master
WHERE "Trial Alias" % 'Trial ABC'  -- Similarity operator (requires pg_trgm)
  AND similarity("Trial Alias", 'Trial ABC') > 0.3  -- Threshold
ORDER BY score DESC
LIMIT 5;
```

**n8n Implementation:**
- If > 1 match: Present options to user
- If 1 match: Auto-select and confirm
- If 0 matches: Ask for clarification

**User Experience:**
```
User: "Show me inventory for Trial ABC"
Assistant: "I found multiple matches for 'Trial ABC':
1. Trial_ABC_v2 (similarity: 85%)
2. Trial ABC 2024 (similarity: 78%)
3. ABC-Extension (similarity: 65%)

Which one did you mean? Please specify by number or full name."

User: "1"
Assistant: "Got it, using Trial_ABC_v2. [Proceeds with query]"
```

---

### 2. SQL Self-Healing Loop

**Scenario: Agent generates invalid SQL**

**Error Types Handled:**
1. **Column not found**: Wrong column name, case, or quotes
2. **Syntax error**: Missing commas, unmatched parentheses
3. **Date format error**: Invalid date conversion
4. **Table not found**: Misspelled table name
5. **Type mismatch**: Wrong data type in comparison

**Retry Strategy:**
```javascript
// n8n Function Node
const maxRetries = 3;
const currentAttempt = $json.attempt || 1;

if (currentAttempt > maxRetries) {
    return {
        json: {
            success: false,
            message: "I couldn't generate a valid query after 3 attempts. Please rephrase your question.",
            error: $json.lastError
        }
    };
}

// Extract error hints
const errorHints = analyzeError($json.error);

// Send back to SQL Generator with context
return {
    json: {
        retry: true,
        attempt: currentAttempt + 1,
        previous_sql: $json.sql,
        error: $json.error,
        hints: errorHints,
        schemas: $json.schemas  // Keep schemas available
    }
};
```

**User Experience:**
```
User: "Show batches expiring soon"
[Attempt 1 - Fails: Column "expiry_date" does not exist]
[Attempt 2 - Corrects to "Expiration date_shelf life" - Success]
Assistant: "[Returns results]"
```

---

### 3. Missing Data Handling

**Scenario: Required data is NULL or missing**

**Re-Evaluation Checker:**
```json
{
    "has_been_reevaluated": false,
    "reevaluation_count": 0,
    "recommendation": "No previous re-evaluation found",
    "reasoning": "No records found in re_evaluation table for batch LOT-45953393. This batch has not been previously submitted for re-evaluation."
}
```

**Regulatory Compliance:**
```json
{
    "regulatory_approval_exists": false,
    "recommendation": "Cannot determine - no regulatory data found",
    "reasoning": "No submissions found in rim table for LY964373. This does not necessarily mean extension is not allowed - regulatory data may be pending or filed under different identifier."
}
```

**Logistics Validator:**
```json
{
    "sufficient_time": null,
    "recommendation": "Cannot calculate - missing shipping timeline",
    "reasoning": "No shipping timeline data found for Germany in ip_shipping_timelines_report. Cannot determine time feasibility without this information."
}
```

**Synthesizer Response:**
```markdown
## Answer: **PARTIAL - MISSING DATA**

Based on available data, I cannot provide a complete YES/NO answer because:

**Missing Information:**
- ✗ Shipping timeline for Germany not found
- ✓ Batch expiry data available
- ⚠ Regulatory data incomplete

**Recommendation:**
Please verify:
1. Is "Germany" the correct country name in our system?
2. Contact regulatory team for LY964373 submission status
3. Once data is available, re-run this check

**Available Data:**
- Batch LOT-45953393 expires on 2025-12-09
- No previous re-evaluation requests found
```

---

### 4. Ambiguous Entity Resolution

**Scenario: User references "that batch" or "the trial"**

**Solution: Use conversation context**

```javascript
// n8n Function - Entity Resolution
const userMessage = $json.message.toLowerCase();
const userContext = $json.user_context;

// Check for pronouns
if (userMessage.includes('that batch') || userMessage.includes('the batch') || userMessage.includes('it')) {
    if (userContext.current_batch) {
        extractedEntities.batch_number = userContext.current_batch;
    } else {
        needsClarification = true;
        clarificationMessage = "Which batch are you referring to? Please provide the batch number.";
    }
}

if (userMessage.includes('the trial') || userMessage.includes('this trial')) {
    if (userContext.current_trial) {
        extractedEntities.trial_alias = userContext.current_trial;
    } else {
        needsClarification = true;
        clarificationMessage = "Which trial are you referring to? Please provide the trial name.";
    }
}
```

**User Experience:**
```
User: "Can we extend batch LOT-45953393?"
Assistant: "[Response about batch LOT-45953393]"
[Context stored: current_batch = "LOT-45953393"]

User: "What trial is it for?"
[System resolves "it" to LOT-45953393]
Assistant: "Batch LOT-45953393 is for trial CT-2004-PSX."

User: "Show me all batches for that trial"
[System resolves "that trial" to CT-2004-PSX]
Assistant: "[Shows all batches for CT-2004-PSX]"
```

---

### 5. Case Sensitivity Edge Cases

**Problem: PostgreSQL column names with spaces/special chars**

**Solution:**
```sql
-- CORRECT (always use double quotes)
SELECT "Batch number", "Trial Alias" FROM batch_master;

-- WRONG
SELECT Batch number, Trial Alias FROM batch_master;  -- Syntax error
SELECT batch number, trial alias FROM batch_master;  -- Column not found
```

**SQL Generator Enforcement:**
- System prompt explicitly requires double quotes
- Example queries demonstrate proper quoting
- Error recovery identifies missing quote issues

---

### 6. Data Type Mismatches

**Problem: TEXT columns with dates, numbers stored as TEXT**

**Solution:**
```sql
-- Date comparisons
WHERE TO_DATE("Expiration date_shelf life", 'YYYY-MM-DD') > CURRENT_DATE

-- Numeric comparisons
WHERE CAST("Total Stock" AS NUMERIC) > 100

-- Handle NULLs
WHERE COALESCE(CAST("Total Stock" AS NUMERIC), 0) > 0

-- Safe date parsing (handles invalid dates)
WHERE TO_DATE(NULLIF(TRIM("Expiration date_shelf life"), ''), 'YYYY-MM-DD') IS NOT NULL
```

---

## TESTING STRATEGY

### Unit Tests

**1. Database Setup Tests**
```python
# test_database_setup.py
def test_table_metadata_exists():
    """Test table_metadata table exists and has data."""
    result = conn.execute("SELECT COUNT(*) FROM table_metadata")
    assert result.fetchone()[0] > 0

def test_fuzzy_indexes_exist():
    """Test trigram indexes are created."""
    result = conn.execute("""
        SELECT indexname FROM pg_indexes
        WHERE indexname LIKE '%_trgm'
    """)
    assert result.rowcount >= 5

def test_fuzzy_matching_works():
    """Test fuzzy matching returns results."""
    result = conn.execute("""
        SELECT * FROM batch_master
        WHERE "Trial Alias" % 'ABC'
        LIMIT 1
    """)
    # Should return at least something if data exists
```

**2. n8n Workflow Tests**
```python
# test_n8n_workflow.py
import requests

def test_webhook_responds():
    """Test n8n webhook is accessible."""
    response = requests.post(
        "http://localhost:5678/webhook/chat",
        json={"session_id": "test", "message": "test"},
        timeout=5
    )
    assert response.status_code == 200

def test_router_agent_classifies_intent():
    """Test Router Agent correctly identifies intent."""
    response = requests.post(
        "http://localhost:5678/webhook/chat",
        json={
            "session_id": "test",
            "message": "Can we extend batch LOT-123?"
        }
    )
    result = response.json()
    assert "intent" in result
    assert result["intent"] in ["shelf_life_extension", "general_query", "clarification_needed"]
```

**3. Gradio UI Tests**
```python
# test_gradio_ui.py
def test_session_creation():
    """Test session ID is generated."""
    sess_id = initialize_session()
    assert sess_id is not None
    assert isinstance(sess_id, str)

def test_history_formatting():
    """Test history is correctly formatted for n8n."""
    history = [
        ("Hello", "Hi there"),
        ("Test", "Response")
    ]
    formatted = format_history_for_n8n(history)
    assert len(formatted) == 4
    assert formatted[0]["role"] == "user"
    assert formatted[1]["role"] == "assistant"
```

---

### Integration Tests

**End-to-End Test Scenarios:**

**Test 1: Shelf-Life Extension Query**
```
Input: "Can we extend batch LOT-45953393 for trial CT-2004-PSX in Germany?"

Expected Flow:
1. Router → shelf_life_extension
2. Re-Evaluation Checker → checks re_evaluation table
3. Regulatory Compliance → checks rim + material_country_requirements
4. Logistics Validator → checks ip_shipping_timelines_report + batch_master
5. Synthesizer → combines results, provides YES/NO/PARTIAL

Expected Output:
- Markdown response with 3 constraint analyses
- Citations to specific table rows
- Clear recommendation
- Data sources listed
```

**Test 2: General Query - Inventory**
```
Input: "Show me all batches expiring in next 30 days"

Expected Flow:
1. Router → general_query
2. SQL Generator → generates SQL
3. Execute SQL → runs query
4. Format Results → returns markdown table

Expected Output:
- SQL query shown
- Table with results
- Row count displayed
```

**Test 3: Fuzzy Matching**
```
Input: "Show inventory for Trial ABC"  (when exact match doesn't exist)

Expected Flow:
1. Router → general_query (with ambiguous trial)
2. Fuzzy Match Handler → searches for similar trials
3. Returns options to user

Expected Output:
- "I found multiple matches:"
- List of 3-5 similar trial names
- Prompt to clarify
```

**Test 4: SQL Error Recovery**
```
Input: "Show me batches" (vague query)

Expected Flow:
1. Router → general_query
2. SQL Generator → generates SQL (might have errors)
3. Execute SQL → fails
4. Retry Loop → corrects SQL
5. Execute SQL → succeeds

Expected Output:
- Results displayed
- No error message shown to user
```

**Test 5: Conversation Context**
```
Input 1: "Tell me about batch LOT-45953393"
Response 1: [Details about batch]

Input 2: "What trial is it for?"
Expected: System resolves "it" to LOT-45953393

Input 3: "Show me all batches for that trial"
Expected: System resolves "that trial" to the trial from previous response
```

---

### Performance Tests

**1. Database Query Performance**
```sql
-- Test fuzzy matching speed
EXPLAIN ANALYZE
SELECT "Trial Alias", similarity("Trial Alias", 'ABC') as score
FROM batch_master
WHERE "Trial Alias" % 'ABC'
ORDER BY score DESC
LIMIT 5;
-- Target: < 100ms

-- Test complex join for shelf-life extension
EXPLAIN ANALYZE
SELECT b.*, r.*, rim.*
FROM batch_master b
LEFT JOIN re_evaluation r ON b."Batch number" = r."Lot Number (Molecule Planner to Complete)"
LEFT JOIN rim ON b."Material ID" = rim.ly_number_c
WHERE b."Batch number" = 'LOT-45953393';
-- Target: < 200ms
```

**2. n8n Workflow Latency**
```python
import time

start = time.time()
response = requests.post(webhook_url, json=payload)
end = time.time()

latency = end - start
assert latency < 10  # Shelf-life extension should complete in < 10s
assert latency < 5   # General query should complete in < 5s
```

---

## DEPLOYMENT GUIDE

### Step-by-Step Deployment

#### Phase 1: Database Setup (15 min)

```bash
cd C:\Users\cools\Downloads\clinical_agent

# 1. Run setup script
python setup_workflow_b.py

# 2. Verify tables created
psql -U postgres -d clinical_supply_chain
\dt  # Should show table_metadata, table_value_index, chat_sessions

# 3. Verify fuzzy matching works
SELECT 'Trial ABC' % 'Trial_ABC_v2' as is_similar;  # Should return true

# 4. Check metadata populated
SELECT COUNT(*) FROM table_metadata;  # Should show 6+ rows
```

---

#### Phase 2: n8n Setup (30 min)

**Option A: Docker**
```bash
# Start n8n
docker run -d ^
  --name n8n ^
  -p 5678:5678 ^
  -v C:\Users\cools\Downloads\clinical_agent\n8n_data:/home/node/.n8n ^
  docker.n8n.io/n8nio/n8n

# Check it's running
curl http://localhost:5678
```

**Option B: npm**
```bash
npm install -g n8n
n8n start
```

**Configure n8n:**
1. Access http://localhost:5678
2. Create account (local only)
3. Add credentials:
   - **PostgreSQL**:
     - Host: localhost
     - Port: 5432
     - Database: clinical_supply_chain
     - User: postgres
     - Password: SUBzero@156
   - **OpenAI**:
     - API Key: [from .env OPENAI_API_KEY]

**Build Workflow:**
1. Create new workflow: "Clinical Assistant Chat"
2. Add nodes following architecture diagram
3. Configure each node with prompts from this document
4. Test each node individually
5. Activate workflow

---

#### Phase 3: Gradio UI (5 min)

```bash
# Install Gradio
pip install gradio requests

# Start UI
python gradio_chat_ui.py

# Access at http://localhost:7860
```

---

#### Phase 4: Integration Testing (20 min)

```bash
# Test full flow
python test_workflow_b.py

# Manual tests via Gradio UI:
# 1. "Can we extend batch LOT-45953393?"
# 2. "Show batches expiring in 30 days"
# 3. "What's the inventory for Trial ABC?"  (test fuzzy matching)
```

---

### Production Deployment (Optional)

**Docker Compose Setup:**
```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: clinical_supply_chain
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: SUBzero@156
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  n8n:
    image: docker.n8n.io/n8nio/n8n
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=changeme
    volumes:
      - n8n_data:/home/node/.n8n
    depends_on:
      - postgres

  gradio:
    build: .
    ports:
      - "7860:7860"
    environment:
      - N8N_WEBHOOK_URL=http://n8n:5678/webhook/chat
    depends_on:
      - n8n

volumes:
  postgres_data:
  n8n_data:
```

---

## RECOMMENDATIONS

### Question 2: Table Metadata - Auto-generate All 40 or Focus on Key Ones?

**RECOMMENDATION: Auto-Generate All 40 Tables**

**Why This is Robust (Not Makeshift):**

1. **Complete System Knowledge**: Router Agent needs comprehensive catalog to route correctly
   - User might ask about any of 40 tables
   - Better to have metadata for all tables than miss one

2. **Scalability**: Auto-generation script ensures consistency
   - No manual errors
   - Easy to update when tables change
   - Can be re-run anytime

3. **Implementation**:
```python
def auto_generate_all_metadata(engine):
    """Auto-generate metadata for all 40 tables."""

    # Get all table names
    tables = pd.read_sql("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name NOT LIKE 'pg_%'
        AND table_name NOT IN ('table_metadata', 'table_value_index', 'chat_sessions', 'watchdog_findings')
        ORDER BY table_name
    """, engine)

    for table_name in tables['table_name']:
        # Get columns
        columns = pd.read_sql(f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """, engine)

        # Infer category from name patterns
        category = infer_category(table_name)

        # Get row count
        count = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {table_name}", engine).iloc[0]['cnt']

        # Generate description (can be enhanced with LLM later)
        description = f"Contains {count} rows with {len(columns)} columns. Key data: {', '.join(columns['column_name'][:5])}"

        # Insert metadata
        conn.execute(text("""
            INSERT INTO table_metadata (...)
            VALUES (...)
            ON CONFLICT (table_name) DO UPDATE ...
        """))

def infer_category(table_name):
    """Infer category from table name."""
    if any(word in table_name.lower() for word in ['inventory', 'stock', 'warehouse', 'batch']):
        return 'inventory'
    elif any(word in table_name.lower() for word in ['order', 'shipment', 'distribution', 'delivery']):
        return 'logistics'
    elif any(word in table_name.lower() for word in ['regulatory', 'rim', 'evaluation', 'approval']):
        return 'regulatory'
    elif any(word in table_name.lower() for word in ['enrollment', 'patient', 'trial']):
        return 'demand'
    elif any(word in table_name.lower() for word in ['manufacturing', 'bom', 'production']):
        return 'manufacturing'
    else:
        return 'other'
```

**Benefits:**
- Router has complete knowledge
- No manual maintenance
- Can enhance descriptions later with GPT-4
- Consistent format across all tables

---

### Question 3: n8n Workflow - Provide JSON Export or Build Manually?

**RECOMMENDATION: Provide JSON Export for Direct Import**

**Why This is Robust (Not Makeshift):**

1. **Consistency**: Manual building is error-prone
   - Easy to misconfigure node connections
   - Typos in prompts
   - Wrong node settings

2. **Version Control**: JSON export is versionable
   - Can track changes
   - Easy to replicate across environments
   - Can be tested programmatically

3. **Speed**: Import takes 30 seconds vs 2 hours manual build

4. **Documentation**: JSON serves as executable documentation
   - Shows exact configuration
   - Can be analyzed by tools
   - Easy to share with team

**Hybrid Approach (Best Practice):**
1. Build workflow once manually (initial design)
2. Export to JSON
3. Version control the JSON
4. For deployment: Import JSON
5. For updates: Edit → Re-export → Version control

**Implementation:**
- I'll provide complete n8n workflow JSON
- You import it via n8n UI: Settings → Import from File
- Workflow includes all nodes, connections, credentials references
- You only need to add actual credential values (API keys)

---

### Additional Robust Solutions

**1. Schema Caching**
- Don't query `information_schema` on every request
- Cache schemas in `table_metadata` with column details
- Refresh cache daily via cron

**2. LLM Response Validation**
- Parse JSON responses from agents
- Validate required fields present
- Fallback to error if malformed

**3. Audit Logging**
- Log all agent decisions to database
- Track: intent classification, tables queried, SQL generated
- Enables debugging and improvement

**4. Rate Limiting**
- Limit queries per session (prevent abuse)
- Track OpenAI API usage
- Alert when approaching limits

**5. Monitoring**
- Database query performance tracking
- n8n workflow execution times
- Error rates by agent
- User satisfaction (optional thumbs up/down)

---

## APPENDIX

### File Structure Summary

```
clinical_agent/
├── WORKFLOW_B_IMPLEMENTATION_PLAN.md  (this file)
├── setup_workflow_b.py
├── gradio_chat_ui.py
├── test_workflow_b.py
├── n8n_workflows/
│   └── clinical_assistant_chat.json
├── agents/
│   ├── router_agent.txt
│   ├── re_evaluation_checker.txt
│   ├── regulatory_compliance.txt
│   ├── logistics_validator.txt
│   ├── sql_generator.txt
│   └── response_synthesizer.txt
└── n8n_data/  (created by Docker)
```

---

### Estimated Implementation Time

| Phase | Time | Complexity |
|-------|------|------------|
| Database Setup | 30 min | Low |
| n8n Installation | 15 min | Low |
| n8n Workflow Build (manual) | 2 hours | High |
| n8n Workflow Import (JSON) | 30 sec | Low |
| Gradio UI | 15 min | Low |
| Testing | 1 hour | Medium |
| **Total (manual)** | **4 hours** | - |
| **Total (with JSON import)** | **2 hours** | - |

---

### Next Steps

1. **Confirm approach**: Approve this architecture
2. **I will provide**:
   - Complete `setup_workflow_b.py` (auto-generates all 40 tables)
   - Complete `gradio_chat_ui.py` (production-ready)
   - Complete n8n workflow JSON export (import-ready)
   - All agent prompt files
   - Test scripts
3. **You execute**:
   - Run `setup_workflow_b.py`
   - Import n8n workflow
   - Start Gradio UI
   - Test end-to-end

Ready to proceed?