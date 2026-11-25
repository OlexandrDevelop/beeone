// beeone: BeeOne sends no usage data anywhere. `frappe.telemetry` stays as a no-op so that the code that reports events
// (onboarding, setup wizard) keeps working.
class TelemetryManager {
	constructor() {
		this.enabled = false;
		this.providers = [];
	}

	capture() {}

	disable() {
		this.enabled = false;
	}

	can_enable() {
		return false;
	}
}

frappe.telemetry = new TelemetryManager();
