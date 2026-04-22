/**
 * Setup instructions for MCP catalog servers, keyed by auth type.
 *
 * Provides per-server guidance (where to get API keys, what scopes to grant, etc.)
 * with a fallback to generic instructions per auth type.
 *
 * All documentation URLs are derived from the actual server URLs in mcp-catalog.yml.
 * OAuth servers: the server URL itself IS the connection point — users open it in
 * their browser to authorize. There is no separate /oauth/authorize endpoint.
 *
 * Phase 10 — fully additive, does not modify any existing file.
 */
// ── Per-server overrides (keyed by server.id from mcp-catalog.yml) ───────
const SERVER_GUIDES = {
    // ── API Key servers ────────────────────────────────────────────────────
    hubspot: {
        steps: [
            { title: 'Open HubSpot Settings', description: 'Go to Settings > Integrations > Private Apps in your HubSpot account.', link: { label: 'Open HubSpot Private Apps', url: 'https://app.hubspot.com/private-apps/' } },
            { title: 'Create a private app', description: 'Click "Create a private app". Give it a name and select the scopes you need (CRM, Marketing, etc.).' },
            { title: 'Copy the token', description: 'After creating the app, copy the access token and paste it below.' },
        ],
        credentialLabel: 'Private App Token',
        credentialPlaceholder: 'pat-xxxxxxxxxxxxxxxxxxxx',
    },
    telnyx: {
        steps: [
            { title: 'Open Telnyx Portal', description: 'Log in to your Telnyx account and go to the API Keys section.', link: { label: 'Open Telnyx API Keys', url: 'https://portal.telnyx.com/#/app/api-keys' } },
            { title: 'Create API Key', description: 'Click "Create API Key", give it a descriptive name.' },
            { title: 'Copy & paste', description: 'Copy the generated key and paste it below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'KEY_xxxxxxxxxxxxxxxxxxxx',
    },
    zapier: {
        steps: [
            { title: 'Open Zapier MCP', description: 'Visit your Zapier MCP settings to find your API key.', link: { label: 'Open Zapier MCP', url: 'https://actions.zapier.com/credentials/' } },
            { title: 'Copy your API key', description: 'Copy the API key from your Zapier MCP credentials page.' },
            { title: 'Paste below', description: 'Paste the key below to connect Zapier to your gateway.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'sk-xxxxxxxxxxxxxxxxxxxx',
    },
    apify: {
        steps: [
            { title: 'Open Apify Console', description: 'Log in to your Apify account and go to Settings > Integrations.', link: { label: 'Open Apify Console', url: 'https://console.apify.com/account/integrations' } },
            { title: 'Copy your API token', description: 'Find your personal API token and copy it.' },
            { title: 'Paste below', description: 'Paste your Apify API token in the field below.' },
        ],
        credentialLabel: 'API Token',
        credentialPlaceholder: 'apify_api_xxxxxxxxxxxxxxxxxxxx',
    },
    needle: {
        steps: [
            { title: 'Open Needle Dashboard', description: 'Log in to your Needle account and navigate to API settings.', link: { label: 'Visit Needle', url: 'https://needle-ai.com' } },
            { title: 'Generate API Key', description: 'Create a new API key for MCP integration.' },
            { title: 'Paste below', description: 'Paste the API key in the field below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'ndk_xxxxxxxxxxxxxxxxxxxx',
    },
    dappier: {
        steps: [
            { title: 'Open Dappier Dashboard', description: 'Log in to your Dappier account.', link: { label: 'Visit Dappier', url: 'https://dappier.com' } },
            { title: 'Get your API key', description: 'Navigate to your developer settings and copy your API key.' },
            { title: 'Paste below', description: 'Paste it in the field below to connect.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your Dappier API key...',
    },
    'close-crm-api': {
        steps: [
            { title: 'Open Close Settings', description: 'Log in to Close and go to Settings > Developer > API Keys.', link: { label: 'Open Close Settings', url: 'https://app.close.com/settings/' } },
            { title: 'Create API Key', description: 'Click "Create API Key" and give it a descriptive name.' },
            { title: 'Paste below', description: 'Copy the key and paste it below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'api_xxxxxxxxxxxxxxxxxxxx',
    },
    'dodo-payments': {
        steps: [
            { title: 'Open Dodo Payments', description: 'Log in to your Dodo Payments dashboard.', link: { label: 'Visit Dodo Payments', url: 'https://dodopayments.com' } },
            { title: 'Navigate to API Keys', description: 'Find the API Keys section in your account settings.' },
            { title: 'Paste below', description: 'Copy your API key and paste it below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your Dodo Payments API key...',
    },
    'mercado-pago': {
        steps: [
            { title: 'Open Mercado Pago Developer', description: 'Go to the Mercado Pago developer portal.', link: { label: 'Open Mercado Pago Dev', url: 'https://www.mercadopago.com/developers' } },
            { title: 'Get your Access Token', description: 'Navigate to your credentials and copy your Access Token.' },
            { title: 'Paste below', description: 'Paste the token in the field below.' },
        ],
        credentialLabel: 'Access Token',
        credentialPlaceholder: 'APP_USR-xxxxxxxxxxxxxxxxxxxx',
    },
    'mercado-libre': {
        steps: [
            { title: 'Open Mercado Libre Developer', description: 'Go to the Mercado Libre developer portal.', link: { label: 'Open ML Developer', url: 'https://developers.mercadolibre.com' } },
            { title: 'Get your Access Token', description: 'Create an app and get your access token from the credentials page.' },
            { title: 'Paste below', description: 'Paste the token in the field below.' },
        ],
        credentialLabel: 'Access Token',
        credentialPlaceholder: 'Enter your Mercado Libre token...',
    },
    shortio: {
        steps: [
            { title: 'Open Short.io Dashboard', description: 'Log in to your Short.io account.', link: { label: 'Open Short.io', url: 'https://short.io' } },
            { title: 'Get your API Key', description: 'Go to Integrations & API to find your API key.' },
            { title: 'Paste below', description: 'Copy and paste the API key below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your Short.io API key...',
    },
    'polar-signals': {
        steps: [
            { title: 'Open Polar Signals Cloud', description: 'Log in to your Polar Signals account.', link: { label: 'Open Polar Signals', url: 'https://cloud.polarsignals.com' } },
            { title: 'Generate API Token', description: 'Go to Settings > API Tokens and create a new token.' },
            { title: 'Paste below', description: 'Paste the token in the field below.' },
        ],
        credentialLabel: 'API Token',
        credentialPlaceholder: 'Enter your Polar Signals token...',
    },
    customgpt: {
        steps: [
            { title: 'Open CustomGPT Dashboard', description: 'Log in to your CustomGPT.ai account.', link: { label: 'Open CustomGPT.ai', url: 'https://app.customgpt.ai' } },
            { title: 'Get your API Key', description: 'Navigate to Settings > API to find your project API key.' },
            { title: 'Paste below', description: 'Copy and paste the key below.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your CustomGPT API key...',
    },
    // ── OAuth2.1 & API Key (Stripe — supports both) ────────────────────────
    stripe: {
        steps: [
            { title: 'Open Stripe Dashboard', description: 'Go to Developers > API keys in your Stripe dashboard.', link: { label: 'Open Stripe API Keys', url: 'https://dashboard.stripe.com/apikeys' } },
            { title: 'Copy your secret key', description: 'Use your Secret key (starts with sk_test_ or sk_live_). For testing, use the test mode key.' },
            { title: 'Paste below', description: 'Paste your Stripe secret key in the field below.' },
        ],
        credentialLabel: 'Secret Key',
        credentialPlaceholder: 'sk_test_xxxxxxxxxxxxxxxxxxxx',
        credentialHint: 'Use a restricted key with only the permissions you need.',
    },
};
// ── Generic fallbacks by auth type ───────────────────────────────────────
const AUTH_TYPE_GUIDES = {
    'Open': {
        steps: [
            { title: 'No configuration needed', description: 'This server is open and does not require any authentication. It will be ready to use immediately after adding.' },
        ],
    },
    'OAuth2.1': {
        steps: [
            { title: 'About OAuth authentication', description: 'This MCP server uses OAuth 2.1 for authentication. The OAuth flow is handled directly by the server when your MCP client connects to it.' },
            { title: 'How it works', description: 'When your MCP client first connects, the server will redirect you to the provider\'s login page. After you grant access, the connection is established automatically.' },
            { title: 'Note', description: 'The server has been registered in your gateway. OAuth authorization will happen automatically when an MCP-compatible client connects to the server URL. You may need to configure your client to connect to this server endpoint.' },
        ],
    },
    'OAuth': {
        steps: [
            { title: 'About OAuth authentication', description: 'This MCP server uses OAuth for authentication. The flow is handled by the server when your MCP client connects.' },
            { title: 'How it works', description: 'Your MCP client will be redirected to the provider to authorize access. After granting permissions, the connection completes automatically.' },
            { title: 'Note', description: 'The server has been added to your gateway. OAuth will be triggered when a client connects.' },
        ],
    },
    'API Key': {
        steps: [
            { title: 'Get your API key', description: 'Log in to the provider\'s website and navigate to their API or developer settings to generate an API key.' },
            { title: 'Copy the key', description: 'Create a new key (or use an existing one) and copy it to your clipboard.' },
            { title: 'Paste below', description: 'Paste the API key in the field below to connect.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your API key...',
        credentialHint: 'Your key is sent securely and stored encrypted.',
    },
    'API': {
        steps: [
            { title: 'Get your API credentials', description: 'Log in to the provider and find your API key or token in the developer/settings section.' },
            { title: 'Paste below', description: 'Paste the credential in the field below.' },
        ],
        credentialLabel: 'API Token',
        credentialPlaceholder: 'Enter your API token...',
        credentialHint: 'Your token is sent securely and stored encrypted.',
    },
    'OAuth2.1 & API Key': {
        steps: [
            { title: 'Choose your method', description: 'This server supports both OAuth and API Key authentication. The simplest option is to use an API key — paste it below to connect immediately.' },
            { title: 'Get your API key', description: 'Log in to the provider\'s website and navigate to their developer settings to generate an API key.' },
            { title: 'Paste below', description: 'Enter your API key to connect. OAuth can also be used when an MCP client connects directly.' },
        ],
        credentialLabel: 'API Key',
        credentialPlaceholder: 'Enter your API key...',
        credentialHint: 'API Key is the simplest method. OAuth is also available via direct client connection.',
    },
};
// ── Public API ────────────────────────────────────────────────────────────
/** Returns the setup guide for a given server, merging per-server overrides with auth-type defaults. */
export function getSetupGuide(serverId, authType) {
    const serverOverride = SERVER_GUIDES[serverId];
    const authDefault = AUTH_TYPE_GUIDES[authType] || AUTH_TYPE_GUIDES['API Key'];
    if (!serverOverride)
        return authDefault;
    return {
        steps: serverOverride.steps || authDefault.steps,
        credentialLabel: serverOverride.credentialLabel || authDefault.credentialLabel,
        credentialPlaceholder: serverOverride.credentialPlaceholder || authDefault.credentialPlaceholder,
        credentialHint: serverOverride.credentialHint || authDefault.credentialHint,
    };
}
/** Returns true if this auth type requires the user to enter an API key / token. */
export function needsCredentialInput(authType) {
    return ['API Key', 'API', 'OAuth2.1 & API Key'].includes(authType);
}
/** Returns true if this auth type uses an OAuth redirect flow (handled by the server URL itself). */
export function needsOAuthFlow(authType) {
    return ['OAuth2.1', 'OAuth'].includes(authType);
}
/** Returns true if the server works immediately without any config. */
export function isOpenAuth(authType) {
    return authType === 'Open';
}
