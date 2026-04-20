# Visual Pipeline Builder - Product Requirements Document (PRD)

## Requirements Description

### Background
- **Business Problem**: Currently, the AI Workflow system enforces a rigid 1:1 relationship between a project and its pipeline configuration (`pipeline-config.json`). Users cannot create multiple workflows for different scenarios (e.g., "Hotfix", "Full Feature", "Discovery") within the same project. Furthermore, pipeline editing is text/list-based, lacking a visual representation of agent interactions.
- **Target Users**: AI Workflow operators, developers, and project managers who need to customize AI agent workflows for different types of tasks.
- **Value Proposition**: Empowers users to intuitively design, store, and switch between multiple custom agent pipelines per project using a visual node-based editor. 

### Feature Overview
- **1:N Project-to-Pipeline Relationship**: Ability to create, save, and delete multiple pipelines within a single project.
- **Visual Canvas Editor**: Drag-and-drop interface to add agents (nodes) and connect them (edges) to define the execution flow.
- **Node Types & Review Logic (Double Pass Architecture)**:
  - The canvas will explicitly support two primary types of execution nodes:
    1. **Agent Node** (e.g., PM, BA, DEV): Executes the primary task based on its custom system prompt. It does *not* receive skill documents.
    2. **Reviewer Node** (e.g., PM_REVIEW, DEV_REVIEW): Specifically designed to evaluate the output of an Agent Node. 
  - **Skill Attachment**: Skills are *only* attached to **Reviewer Nodes**. When a user clicks a Reviewer Node, the sidebar allows them to select which `.tessl/tiles/.../SKILL.md` documents should be injected into that specific reviewer's prompt.
  - This explicit visual representation preserves the existing "Double Pass" architecture, making the review steps and their associated skills fully transparent on the canvas (e.g., user must draw a connection: `DEV -> DEV_REVIEW`).

### Detailed Requirements
- **Data Structure**:
  - Migrate from a single `pipeline-config.json` to a dictionary or directory of pipelines.
  - E.g., `pipelines/` directory inside `.ai-workflow/` or `projects/{name}/` containing `{pipeline_id}.json`.
  - Each pipeline JSON must store: `nodes` (id, type/agent, position, config) and `edges` (from, to).
- **User Interaction**:
  - **Dashboard > Pipeline Tab**: Shows a sidebar/dropdown to select the active pipeline or create a new one.
  - **Canvas**: Central area showing the graph. 
  - **Node Click**: Opens a modal or right-sidebar showing the "Agents" tab functionality (Instructions Editor, Skills selector), but tied to `pipeline_id` + `node_id`.

## Design Decisions

### Technical Approach
- **Frontend Stack**: Vanilla HTML/JS/CSS (matching current `dashboard/index.html`).
- **Graph Library**: Use **LiteGraph.js** or **Drawflow** (via CDN) as they are excellent, lightweight Vanilla JS libraries for node-based graph editing without requiring a React/Vue build step. (Recommendation: *Drawflow* is very modern and DOM-based, easy to style with CSS).
- **Backend (FastAPI)**:
  - `GET /api/projects/{name}/pipelines` -> List pipelines.
  - `POST /api/projects/{name}/pipelines` -> Create pipeline.
  - `GET /api/projects/{name}/pipelines/{id}` -> Get graph and node configs.
  - `PUT /api/projects/{name}/pipelines/{id}` -> Save graph and node configs.
- **Orchestrator Integration**: `cli.py` and the orchestrator prompt must be updated to read the *active* pipeline's graph structure to determine the sequence of agents, instead of the hardcoded `stages` array.

### Constraints
- **Compatibility**: Must gracefully migrate or handle existing `pipeline-config.json` files by converting them into the first "Default Pipeline".
- **Execution**: The orchestrator currently relies on a linear sequence. A graph allows branching. For v1.0, we will support linear or simple branching, but the orchestrator must traverse the graph properly (e.g., topologically).

## Acceptance Criteria

### Functional Acceptance
- [ ] Users can create a new pipeline in a project.
- [ ] Users can see a visual canvas and drag/drop agent nodes.
- [ ] Users can connect nodes to define the pipeline flow.
- [ ] Users can click a node to edit its specific prompt and skills.
- [ ] Saving the canvas correctly persists the graph structure in the backend.
- [ ] The execution engine (`cli.py` / orchestrator) can read the active pipeline graph and execute the agents in the connected order.

### Quality Standards
- [ ] Visual canvas integrates smoothly with the existing dark theme.
- [ ] Backward compatibility: Existing projects load their linear pipelines into the visual canvas automatically.

## Execution Phases

### Phase 1: Data Model & Backend (BA & DEV)
**Goal**: Prepare the backend to store multiple pipelines and node-specific configs.
- [ ] Update `server.py` endpoints for CRUD operations on pipelines.
- [ ] Create a migration function for legacy `pipeline-config.json`.

### Phase 2: Frontend Visual Canvas (DESIGN & DEV)
**Goal**: Integrate the graph library into `dashboard/index.html`.
- [ ] Add Drawflow/LiteGraph via CDN.
- [ ] Build the Pipeline tab UI (Pipeline selector + Canvas).
- [ ] Implement node creation, connection, and deletion.

### Phase 3: Contextual Configuration (DEV)
**Goal**: Bind node clicks to the instruction/skills editor.
- [ ] Implement right-sidebar or modal on node click.
- [ ] Save contextual instructions per node.

### Phase 4: Orchestrator Engine Update (DEV)
**Goal**: Make the AI actually follow the graph.
- [ ] Update `cli.py` to fetch the active pipeline graph.
- [ ] Update `orchestrator/instructions.md` to parse graph transitions (Node A -> Node B) instead of flat arrays.

---
**Document Version**: 1.0
**Quality Score**: 95/100
