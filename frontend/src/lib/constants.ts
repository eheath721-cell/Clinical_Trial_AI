export const INQUIRY_STATUS: Record<string, { label: string; tone: "neutral" | "brand" | "eligible" | "uncertain" | "ineligible" }> = {
  draft: { label: "Draft", tone: "neutral" },
  ready: { label: "Ready to send", tone: "brand" },
  sent_by_user: { label: "Sent", tone: "brand" },
  response_received: { label: "Response received", tone: "uncertain" },
  prescreen_scheduled: { label: "Pre-screen scheduled", tone: "eligible" },
  screening: { label: "Screening", tone: "eligible" },
  enrolled: { label: "Enrolled", tone: "eligible" },
  not_eligible: { label: "Not eligible", tone: "ineligible" },
  declined: { label: "Declined", tone: "neutral" },
  closed: { label: "Closed", tone: "neutral" },
};
