const has = (p, ...keys) => {
    const txt = `${p.name ?? ''} ${p.description ?? ''} ${p.persona_agent?.persona_class ?? ''}`.toLowerCase();
    return keys.some((k) => txt.includes(k));
};
export const TEAM_BUNDLES = [
    {
        id: 'brainstorm',
        name: 'Brainstorm Team',
        description: 'Creative + Analyst + Product coverage',
        match: (p) => has(p, 'creative', 'design', 'brand', 'analyst', 'data', 'product', 'roadmap'),
        maxPick: 6,
    },
    {
        id: 'incident',
        name: 'Incident Team',
        description: 'Ops + Engineering + Notes',
        match: (p) => has(p, 'devops', 'engineer', 'infra', 'incident', 'sre', 'secretary', 'assistant', 'minutes'),
        maxPick: 6,
    },
    {
        id: 'standup',
        name: 'Standup Team',
        description: 'Lightweight daily sync',
        match: (p) => has(p, 'assistant', 'secretary', 'engineer', 'product', 'analyst'),
        maxPick: 5,
    },
];
