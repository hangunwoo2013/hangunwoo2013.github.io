/* B-ROUTE public browser configuration. Never put API keys or secrets here.
 * Leave apiBaseUrl empty when frontend and FastAPI are served by the same Cloud Run origin.
 * For a separately hosted frontend, set only the API server origin, e.g. https://broute-api-xxxxx.run.app
 */
window.BROUTE_CONFIG = Object.freeze({
  apiBaseUrl: ""
});
