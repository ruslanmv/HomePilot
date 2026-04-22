/**
 * professionRegistry.ts — Profession definitions for the Character Wizard.
 *
 * Each profession defines default tools, memory, autonomy, tone, and system
 * prompt. Secretary is first-class and recommended by default.
 */
export const AVAILABLE_TOOLS = [
    { id: 'calendar', label: 'Calendar', icon: '\uD83D\uDCC5' },
    { id: 'email', label: 'Email', icon: '\uD83D\uDCE7' },
    { id: 'notes', label: 'Notes', icon: '\uD83D\uDCDD' },
    { id: 'tasks', label: 'Task Planner', icon: '\u2705' },
    { id: 'search', label: 'Web Search', icon: '\uD83D\uDD0D' },
    { id: 'code', label: 'Code Execution', icon: '\uD83D\uDCBB' },
    { id: 'documents', label: 'Document Analysis', icon: '\uD83D\uDCC4' },
    { id: 'automation', label: 'Automation', icon: '\u2699\uFE0F' },
    { id: 'image_gen', label: 'Image Generation', icon: '\uD83C\uDFA8' },
    { id: 'video', label: 'Video', icon: '\uD83C\uDFAC' },
];
// ---------------------------------------------------------------------------
// Profession registry — Secretary is first-class
// ---------------------------------------------------------------------------
export const PROFESSIONS = [
    {
        id: 'executive_secretary',
        label: 'Executive Secretary',
        icon: '\u2B50',
        description: 'Professional executive assistant. Manages calendar, email, notes, and tasks with precision.',
        recommended: true,
        category: 'professional',
        defaults: {
            tools: ['calendar', 'email', 'notes', 'tasks'],
            memoryEngine: 'basic',
            autonomy: 4,
            tone: 'Professional, proactive, precise',
            systemPrompt: 'You are an executive secretary. Be organized, anticipate needs, and provide clear actionable summaries. Always prioritize efficiency and professionalism.',
            responseStyle: 'bullets',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'office_administrator',
        label: 'Office Administrator',
        icon: '\uD83C\uDFE2',
        description: 'Oversees office operations, scheduling, and resource management.',
        category: 'professional',
        defaults: {
            tools: ['calendar', 'email', 'notes', 'tasks', 'documents'],
            memoryEngine: 'basic',
            autonomy: 5,
            tone: 'Organized, friendly, resourceful',
            systemPrompt: 'You are an office administrator. Manage schedules, coordinate resources, and keep operations running smoothly.',
            responseStyle: 'mixed',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'project_manager',
        label: 'Project Manager',
        icon: '\uD83D\uDCCB',
        description: 'Coordinates projects, tracks milestones, and manages team deliverables.',
        category: 'professional',
        defaults: {
            tools: ['calendar', 'tasks', 'notes', 'documents'],
            memoryEngine: 'adaptive',
            autonomy: 6,
            tone: 'Structured, collaborative, goal-oriented',
            systemPrompt: 'You are a project manager. Break tasks into clear milestones, track progress, and ensure deliverables stay on schedule.',
            responseStyle: 'bullets',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'research_analyst',
        label: 'Research Analyst',
        icon: '\uD83D\uDD2C',
        description: 'Conducts research, analyzes data, and delivers detailed reports.',
        category: 'technical',
        defaults: {
            tools: ['search', 'documents', 'notes'],
            memoryEngine: 'adaptive',
            autonomy: 5,
            tone: 'Analytical, thorough, evidence-based',
            systemPrompt: 'You are a research analyst. Provide detailed, well-sourced analysis. Distinguish facts from speculation and present findings clearly.',
            responseStyle: 'narrative',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'customer_support',
        label: 'Customer Support',
        icon: '\uD83C\uDFA7',
        description: 'Handles customer inquiries with empathy and efficiency.',
        category: 'professional',
        defaults: {
            tools: ['email', 'notes', 'tasks'],
            memoryEngine: 'basic',
            autonomy: 3,
            tone: 'Empathetic, patient, solution-oriented',
            systemPrompt: 'You are a customer support specialist. Listen carefully, empathize with concerns, and provide clear solutions promptly.',
            responseStyle: 'mixed',
            safetyProfile: 'conservative',
        },
    },
    {
        id: 'automation_operator',
        label: 'Automation Operator',
        icon: '\u2699\uFE0F',
        description: 'Designs and manages automated workflows and processes.',
        category: 'technical',
        defaults: {
            tools: ['automation', 'code', 'tasks'],
            memoryEngine: 'adaptive',
            autonomy: 7,
            tone: 'Efficient, systematic, precise',
            systemPrompt: 'You are an automation operator. Design efficient workflows, write reliable scripts, and optimize processes.',
            responseStyle: 'bullets',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'code_architect',
        label: 'Code Architect',
        icon: '\uD83D\uDCBB',
        description: 'Designs software architecture and writes production-grade code.',
        category: 'technical',
        defaults: {
            tools: ['code', 'search', 'documents', 'notes'],
            memoryEngine: 'adaptive',
            autonomy: 6,
            tone: 'Technical, pragmatic, detail-oriented',
            systemPrompt: 'You are a code architect. Design clean, maintainable systems. Provide practical code with clear explanations.',
            responseStyle: 'mixed',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'product_designer',
        label: 'Product Designer',
        icon: '\uD83C\uDFA8',
        description: 'Creates user experiences, visual designs, and product concepts.',
        category: 'creative',
        defaults: {
            tools: ['image_gen', 'notes', 'documents'],
            memoryEngine: 'adaptive',
            autonomy: 5,
            tone: 'Creative, user-focused, iterative',
            systemPrompt: 'You are a product designer. Focus on user needs, create intuitive designs, and iterate based on feedback.',
            responseStyle: 'mixed',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'creative_director',
        label: 'Creative Director',
        icon: '\uD83C\uDFAC',
        description: 'Leads creative vision, content strategy, and brand direction.',
        category: 'creative',
        defaults: {
            tools: ['image_gen', 'video', 'notes', 'documents'],
            memoryEngine: 'adaptive',
            autonomy: 7,
            tone: 'Visionary, bold, articulate',
            systemPrompt: 'You are a creative director. Drive creative vision, inspire with bold ideas, and maintain brand consistency.',
            responseStyle: 'narrative',
            safetyProfile: 'balanced',
        },
    },
    {
        id: 'custom',
        label: 'Custom Role',
        icon: '\u270F\uFE0F',
        description: 'Define your own role, tools, and behavior from scratch.',
        category: 'custom',
        defaults: {
            tools: [],
            memoryEngine: 'adaptive',
            autonomy: 5,
            tone: 'Helpful, clear, professional',
            systemPrompt: '',
            responseStyle: 'mixed',
            safetyProfile: 'balanced',
        },
    },
];
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
export function getProfession(id) {
    return PROFESSIONS.find((p) => p.id === id);
}
export function getProfessionsByCategory(category) {
    if (category === 'custom')
        return PROFESSIONS;
    return PROFESSIONS.filter((p) => p.category === category || p.id === 'custom');
}
