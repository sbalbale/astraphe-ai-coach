/**
 * Bumped on every client-side navigation (root layout `afterNavigate`).
 * Analysis pages read `epoch` in a `$effect` so fetches re-run after navbar clicks,
 * not only on full page reload.
 */
class AnalysisNavEpoch {
	epoch = $state(0);

	bump() {
		this.epoch += 1;
	}
}

export const analysisNavEpoch = new AnalysisNavEpoch();
