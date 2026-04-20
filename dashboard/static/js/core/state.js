/**
 * Centralized application state.
 * Replaces scattered global variables from the old index.html.
 */
const AppState = {
    currentProject: '',
    allProjects: [],
    baseBranches: {},
    currentAgent: '',
    allArtifacts: [],
    activeFilters: new Set(['todo', 'in-progress', 'done']),
    backlogItems: [],
    sessions: {},
    user: null,
    pipelines: [],
    currentPipelineId: null,
    projectAgents: [],

    // Pending modal state
    pendingDeleteId: null,
    pendingRunId: null,
    pendingFiles: [],

    // Load sequence counter (prevents race conditions)
    _loadSeq: 0,

    reset() {
        this.currentProject = '';
        this.currentAgent = '';
        this.allArtifacts = [];
        this.backlogItems = [];
        this.pipelines = [];
        this.currentPipelineId = null;
        this.projectAgents = [];
        this.pendingDeleteId = null;
        this.pendingRunId = null;
        this.pendingFiles = [];
    },
};

// Expose to window so inline event handlers (e.g. <select onchange="window.AppState...">)
// can access it. `const` declarations in non-module scripts live in script scope only.
window.AppState = AppState;
