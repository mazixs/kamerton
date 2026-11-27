export const CLIENT_BASE_STORAGE = "kamerton_client_base";

// Адрес из формы используется в примерах и никогда не меняет адрес запросов консоли.
export function clientBase(address, mode) {
  const raw = address.trim();
  try {
    const url = new URL(raw);
    if (!/^https?:\/\/[^\s/@?#%\\]+(?:\/v1)?\/?$/i.test(raw) || url.username || url.password ||
        !/^[a-z\d.:[\]_-]+$/i.test(url.hostname) || (mode === "owner" && url.protocol !== "https:")) return null;
    return url.origin + "/v1";
  } catch {
    return null;
  }
}

export function requestExamples(base, selected, auth, file) {
  if (!base) return { curl: "—", py: "—", models: "—", agent: "—" };
  const model = selected || "kamerton";
  const separator = " \\\n  ";
  const bearer = auth ? ['-H "Authorization: Bearer $KAMERTON_API_KEY"'] : [];
  return {
    curl: ["curl --fail-with-body '" + base + "/audio/transcriptions'", ...bearer,
      "-F 'model=" + model + "'", "-F 'file=@" + file + "'"].join(separator),
    models: ["curl --fail-with-body '" + base + "/models'", ...bearer].join(separator),
    py: (auth ? "import os\n" : "") + "from openai import OpenAI\n\n" +
      'client = OpenAI(base_url="' + base + '", api_key=' + (auth ? 'os.environ["KAMERTON_API_KEY"]' : '"not-needed"') + ')\n' +
      'with open("' + file + '", "rb") as audio:\n    result = client.audio.transcriptions.create(model="' + model +
      '", file=audio)\nprint(result.text)',
    agent: [
      "Integrate Kamerton as an OpenAI-compatible speech-to-text service.",
      "Base URL: " + base,
      "Preferred model ID: " + model,
      ...(auth ? ["Read KAMERTON_API_KEY from the environment. Send it as an Authorization: Bearer header and redact it from logs and error messages."] : []),
      "",
      "1. Call GET /models under the base URL. Read the downloaded model IDs from data[].id and use the preferred ID if listed. If it is absent, report the available IDs and ask which model to use.",
      "2. Call POST /audio/transcriptions under the base URL with multipart/form-data. Send the audio as file, the chosen ID as model, and json as response_format. Allow time for model startup and read the transcript from the text field.",
      "3. Read error.code and error.message on failures. For 401 check the API key. For 404 refresh the model list. For 503 honor Retry-After when present and report a model startup failure.",
    ].join("\n"),
  };
}
