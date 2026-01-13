export type Media = {
images?: string[]
video_url?: string
}

export type Msg = {
id: string
role: 'user' | 'assistant'
text: string
media?: Media | null
pending?: boolean
}
