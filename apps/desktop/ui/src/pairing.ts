import type { HubState, Me } from "./api";

export type PairingCamera = "phone" | "glasses";

/** A pairing QR is complete only when the hub sees the source it asked the phone to open. */
export function pairedCamera(state: HubState | null, expected: PairingCamera): boolean {
  return !!state?.camera_connected && state.camera?.source === expected;
}

/** Learning is anonymous on optional-auth hubs. Account UI belongs only in a required-auth connection flow. */
export function hubRequiresAccount(me: Me | null): boolean {
  return !!me && me.auth === "required" && !me.user;
}
