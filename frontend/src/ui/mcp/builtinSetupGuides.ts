/**
 * Setup guides for builtin MCP servers that require configuration.
 *
 * These are the optional servers from server_catalog.yaml that have
 * `requires_config` set (GOOGLE_OAUTH, SLACK_TOKEN, etc.).
 *
 * The guides provide prerequisite steps shown in the ServerConfigDrawer
 * before the user enters their credentials.
 */

export type BuiltinSetupStep = {
  title: string
  description: string
  link?: { label: string; url: string }
}

export type BuiltinSetupGuide = {
  title: string
  subtitle: string
  prerequisiteSteps: BuiltinSetupStep[]
  docUrl?: string
}

const BUILTIN_GUIDES: Record<string, BuiltinSetupGuide> = {
  'hp-gmail': {
    title: 'Connect Gmail',
    subtitle: 'Search, read, draft, and send emails',
    docUrl: 'https://console.cloud.google.com/apis/credentials',
    prerequisiteSteps: [
      {
        title: 'Create a Google Cloud project',
        description:
          'Go to the Google Cloud Console, create a new project (or select existing), then enable the Gmail API.',
        link: {
          label: 'Open Google Cloud Console',
          url: 'https://console.cloud.google.com/apis/library/gmail.googleapis.com',
        },
      },
      {
        title: 'Create OAuth credentials',
        description:
          "Navigate to APIs & Services → Credentials → Create Credentials → OAuth client ID. Choose 'Desktop app'.",
        link: {
          label: 'Open Credentials Page',
          url: 'https://console.cloud.google.com/apis/credentials',
        },
      },
      {
        title: 'Copy Client ID & Secret',
        description:
          'After creating the OAuth client, copy the Client ID and Client Secret to enter below.',
      },
    ],
  },
  'hp-google-calendar': {
    title: 'Connect Google Calendar',
    subtitle: 'View, create, and manage calendar events',
    docUrl: 'https://console.cloud.google.com/apis/credentials',
    prerequisiteSteps: [
      {
        title: 'Enable Google Calendar API',
        description:
          'In Google Cloud Console, enable the Google Calendar API for your project.',
        link: {
          label: 'Enable Calendar API',
          url: 'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com',
        },
      },
      {
        title: 'Create OAuth credentials',
        description:
          "If you already have OAuth credentials (e.g., from Gmail setup), you can reuse them. Otherwise, create new ones under APIs & Services → Credentials.",
        link: {
          label: 'Open Credentials Page',
          url: 'https://console.cloud.google.com/apis/credentials',
        },
      },
      {
        title: 'Copy Client ID & Secret',
        description: 'Copy the Client ID and Client Secret to enter below.',
      },
    ],
  },
  'hp-microsoft-graph': {
    title: 'Connect Microsoft 365',
    subtitle: 'Outlook mail, calendar, OneDrive, and Microsoft services',
    docUrl:
      'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
    prerequisiteSteps: [
      {
        title: 'Register an Azure AD app',
        description:
          "Go to Azure Portal → App registrations → New registration. Choose your supported account types.",
        link: {
          label: 'Open Azure App Registrations',
          url: 'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
        },
      },
      {
        title: 'Add API permissions',
        description:
          'Under API permissions, add Microsoft Graph delegated permissions: Mail.Read, Mail.Send, Calendars.ReadWrite, User.Read.',
      },
      {
        title: 'Enable public client flow',
        description:
          "For device_code auth (recommended), go to Authentication and enable 'Allow public client flows'.",
      },
    ],
  },
  'hp-slack': {
    title: 'Connect Slack',
    subtitle: 'Read channels, search messages, post updates',
    docUrl: 'https://api.slack.com/apps',
    prerequisiteSteps: [
      {
        title: 'Create a Slack App',
        description:
          "Go to the Slack API portal and create a new app. Choose 'From scratch' and select your workspace.",
        link: {
          label: 'Create Slack App',
          url: 'https://api.slack.com/apps?new_app=1',
        },
      },
      {
        title: 'Add Bot Scopes',
        description:
          'Under OAuth & Permissions, add these bot token scopes: channels:read, channels:history, chat:write, users:read, search:read.',
      },
      {
        title: 'Install to Workspace',
        description:
          "Click 'Install to Workspace', authorize, then copy the Bot User OAuth Token (starts with xoxb-).",
      },
    ],
  },
  'hp-github': {
    title: 'Connect GitHub',
    subtitle: 'Repositories, issues, pull requests, and code search',
    docUrl: 'https://github.com/settings/tokens',
    prerequisiteSteps: [
      {
        title: 'Create a Personal Access Token',
        description:
          'Go to GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens (recommended).',
        link: {
          label: 'Create GitHub Token',
          url: 'https://github.com/settings/tokens?type=beta',
        },
      },
      {
        title: 'Select permissions',
        description:
          'For fine-grained: select repos and add Contents (read), Issues (read/write), Pull requests (read/write). For classic: select repo, read:org.',
      },
      {
        title: 'Generate & copy token',
        description:
          'Generate the token and copy it immediately — tokens are only shown once.',
      },
    ],
  },
  'hp-notion': {
    title: 'Connect Notion',
    subtitle: 'Search, read, and create pages and databases',
    docUrl: 'https://www.notion.so/my-integrations',
    prerequisiteSteps: [
      {
        title: 'Create a Notion integration',
        description:
          "Go to Notion's integrations page and click 'New integration'. Give it a name and select your workspace.",
        link: {
          label: 'Create Notion Integration',
          url: 'https://www.notion.so/my-integrations',
        },
      },
      {
        title: 'Copy the Integration Token',
        description:
          'After creating the integration, copy the Internal Integration Token (starts with ntn_).',
      },
      {
        title: 'Share pages with integration',
        description:
          'In Notion, open any page/database you want accessible, click Share → Invite, and add your integration.',
      },
    ],
  },
  'hp-teams': {
    title: 'Connect Microsoft Teams',
    subtitle: 'Teams channels, messages, and collaboration',
    docUrl:
      'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
    prerequisiteSteps: [
      {
        title: 'Register an Azure AD app',
        description:
          "Same app as Microsoft Graph, or create a new one in Azure Portal → App registrations.",
        link: {
          label: 'Open Azure App Registrations',
          url: 'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
        },
      },
      {
        title: 'Add Teams permissions',
        description:
          'Add Microsoft Graph delegated permissions: Team.ReadBasic.All, Channel.ReadBasic.All, ChannelMessage.Read.All, Chat.Read.',
      },
      {
        title: 'Copy Application ID',
        description:
          'Copy the Application (client) ID from the Overview page.',
      },
    ],
  },
}

/** Get the setup guide for a builtin server by its server ID. */
export function getBuiltinSetupGuide(
  serverId: string,
): BuiltinSetupGuide | null {
  return BUILTIN_GUIDES[serverId] || null
}

/** Check if a server has a builtin setup guide. */
export function hasBuiltinSetupGuide(serverId: string): boolean {
  return serverId in BUILTIN_GUIDES
}
