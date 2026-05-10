export type Tier = 1 | 2 | 3 | 4;

export interface NodeSummary {
  node_id: string;
  label: string;
  online: boolean;
  last_seen: string;
  scene?: string;
  livekit_room?: string;
}

export interface EventRecord {
  id: string;
  incident_id: string;
  node_id: string;
  homeowner_id: string;
  tier: Tier;
  tier_label: "AMBIENT" | "NOTICE" | "ALERT" | "CRITICAL";
  behavior_pattern: string;
  confidence: number;
  scene: string;
  suspect_description?: string;
  one_line_summary: string;
  timestamp: string;
  clip_url?: string;
  thumb_url?: string;
  yolo_classes: string[];
  actions_taken: string[];
}

export interface QueryRequest {
  question: string;
  conversation_id?: string;
  scope?: "history" | "live" | "auto";
}

export type QueryStreamEvent =
  | { type: "token"; text: string }
  | { type: "clip"; clip: { event_id: string; thumb_url: string; timestamp: string; tier: Tier; one_line: string } }
  | { type: "done" };

export interface PairingChallenge {
  pair_code: string;
  expires_at: string;
  qr_payload: string;
}

export interface ContactRule {
  id: string;
  name: string;
  channel: "sms" | "voice" | "email";
  destination: string;
  min_tier: Tier;
}
