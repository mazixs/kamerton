import { useState } from "react";
import { FileAudio, Mic } from "lucide-react";
import { useConsole } from "@/app/use-console";
import { CopyButton } from "@/components/copy-button";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { microphoneAvailable } from "./audio.js";
import { HistoryPanel } from "./history-panel";
import { transcriptText } from "./history.js";
import { Latency, Transcript } from "./transcript";
import { useHistory } from "./use-history.js";
import { useMicrophone } from "./use-microphone.js";
import { useTranscription } from "./use-transcription.js";
import "./dictation.css";

export function Dictation({ active }) {
  const { api, status, statusError, heads, t, lang, subscribe, refreshStatus } = useConsole();
  const [mode, setMode] = useState("mic");
  const [file, setFile] = useState(null);
  const [diarize, setDiarize] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const history = useHistory(active);
  const mic = useMicrophone(active);
  const transcription = useTranscription({
    api, status, subscribe, refreshStatus,
    onResult(filename, result) {
      if (history.save(filename, result)) setHistoryPage(0);
    },
  });
  const isMic = mode === "mic";
  const recording = mic.phase === "recording";
  const starting = mic.phase === "starting";
  const ready = status?.status === "ready";
  const canUseMic = microphoneAvailable();
  const busy = starting || Boolean(transcription.stage);
  const diarizationAvailable = !isMic && ["parakeet", "sherpa"].includes(status?.engine?.runtime);
  const phase = transcription.stage || (transcription.result ? (transcription.result.cached ? "cached" : "complete") : null);
  const percent = status?.diarization?.progress;
  const progress = phase === "diarization_download" && Number.isInteger(percent) && percent >= 0 && percent <= 100
    ? ` ${percent}%` : "";
  const source = isMic ? mic.error ? t("mic.error", { message: mic.error })
    : recording ? t("audio.live") : starting ? t("audio.permission")
      : !canUseMic ? t("mic.blockedTitle") : "" : file?.name;
  const service = !status ? statusError?.message || t("audio.awaitStatus")
    : !ready ? t("audio.notReady", { state: t("state." + status.status) }) : "";
  const sourceState = [source || (!service ? t(isMic ? "audio.idle" : "audio.pick") : ""), service].filter(Boolean).join(" · ");
  const text = transcriptText(transcription.result, t);

  function chooseFile(value) {
    if (!value || recording || starting) return;
    transcription.reset();
    setFile(value);
    setMode("file");
  }

  function changeSource(value) {
    if (!value || value === mode) return;
    transcription.reset();
    setMode(value);
  }

  async function toggleRecording() {
    if (recording) {
      const wav = mic.stop();
      if (!wav) transcription.reset("test.tooShort");
      else if (ready) await transcription.submit(wav, "microphone.wav", { source: "microphone" });
      else transcription.reset("audio.notSent");
    } else if (!busy && ready && canUseMic) {
      transcription.reset();
      await mic.start();
    }
  }

  return (
    <>
      <Layout variant="dictdesk">
        <div
          className={cn("rack", dragging && "over")}
          id="drop"
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
          onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}
        >
          <Layout variant="face" dataSet={{ running: recording }}>
            <Layout variant="faceinfo" role="status">
              <Heading level={2}><i className="led" aria-hidden="true" /><span id="source-title">{t(isMic ? (recording ? "audio.recording" : "audio.mic") : "audio.file")}</span></Heading>
              <p id="source-state">{sourceState}</p>
            </Layout>
            <Layout variant="scope" aria-hidden="true">
              <i className="idlepoint" id="idlepoint" hidden={recording && !mic.reduceMotion} />
              <canvas ref={mic.canvas} id="meter" width={480} height={64} hidden={!recording || mic.reduceMotion} />
            </Layout>
          </Layout>
          <Layout variant="rackcontrols">
            <ToggleGroup type="single" value={mode} onValueChange={changeSource} className="modes" aria-label={t("audio.source")}>
              <ToggleGroupItem id="mic-mode" value="mic"><Mic data-icon="inline-start" aria-hidden="true" />{t("audio.mic")}</ToggleGroupItem>
              <ToggleGroupItem id="file-mode" value="file" disabled={recording || starting}><FileAudio data-icon="inline-start" aria-hidden="true" />{t("audio.file")}</ToggleGroupItem>
            </ToggleGroup>
            <Button type="button" id="btn-record" className="primary" hidden={!isMic} disabled={busy || (!recording && (!ready || !canUseMic))} onClick={toggleRecording}>
              {t(recording ? "btn.recordStop" : "audio.record")}
            </Button>
            <div className="sourcebtns" id="file-actions" hidden={isMic}>
              <label className="filepick">
                <span>{t("btn.file")}</span>
                <Input type="file" id="file-input" accept="audio/*,.wav,.webm,.opus,.mp3,.ogg,.flac,.m4a" aria-label={t("btn.file")} disabled={recording || starting} onChange={(event) => chooseFile(event.target.files[0])} />
              </label>
              <Button type="button" id="btn-send" className="primary" disabled={!file || !ready || busy} onClick={() => transcription.submit(file, file?.name, { diarize: diarizationAvailable && diarize })}>
                {t("audio.send")}
              </Button>
            </div>
            <Field id="diarization-option" orientation="horizontal" className="check" hidden={!diarizationAvailable} data-disabled={!ready || busy}>
              <Checkbox id="diarization-enabled" checked={diarize} onCheckedChange={(value) => setDiarize(value === true)} disabled={!ready || busy} aria-describedby="diarization-note" />
              <FieldLabel htmlFor="diarization-enabled">{t("diarization.enable")}</FieldLabel>
            </Field>
            <FieldDescription className="help" id="diarization-note" hidden={!diarizationAvailable}>
              {t(status?.diarization_installed ? "diarization.installed" : "diarization.download")}
            </FieldDescription>
          </Layout>
        </div>
        <section className="result" aria-labelledby="transcript-title">
          <Layout variant="titleline">
            <Heading level={2} id="transcript-title">{t("audio.transcript")}</Heading>
            <CopyButton t={t} target="result-text" value={text} active={active} className="copy" hidden={!text} />
          </Layout>
          <p className="audio-progress" id="audio-progress" role="status">
            {phase ? t("audio.stage." + phase) + progress : transcription.error ? t("audio.stage.failed") : ""}
          </p>
          <div className={cn("transcript", !text && "empty", transcription.error && "error")} id="result-text" tabIndex={text ? 0 : -1}>
            {transcription.result ? <Transcript result={transcription.result} t={t} />
              : transcription.stage ? "" : transcription.error?.message || t(transcription.message)}
          </div>
          <Latency result={transcription.result} t={t} />
        </section>
        <HistoryPanel {...history} page={historyPage} setPage={setHistoryPage} t={t} lang={lang} active={active} />
      </Layout>
      <DictationOverview status={status} heads={heads} t={t} />
    </>
  );
}

function DictationOverview({ status, heads, t }) {
  const engine = status?.engine;
  const name = !status ? t("audio.unknownModel") :
    heads.find((head) => head.id === engine?.variant)?.title || engine?.variant || t("audio.noModel");
  const punctuation = engine?.runtime === "sherpa" ? (engine.punctuation === "off" ? "off" : "on")
    : engine?.runtime === "gigaam_v4" ? "on" : engine?.runtime === "gigastt" ? engine.punctuation : null;
  const itn = engine?.runtime === "gigaam_v4" ? "on" : engine?.runtime === "gigastt" ? engine.itn : null;
  const timings = (status?.metrics?.recent || []).map((record) => record.elapsed).filter(Number.isFinite).sort((a, b) => a - b);
  const middle = Math.floor(timings.length / 2);
  const median = timings.length % 2 ? timings[middle] : (timings[middle - 1] + timings[middle]) / 2;
  return (
    <aside className="dictaside">
      <section className="configbox">
        <Heading level={2}>{t("audio.config")}</Heading>
        <Layout variant="identity"><strong id="cur-model">{name}</strong><Badge variant="secondary" id="cur-id" hidden={!engine?.variant}>{engine?.variant}</Badge></Layout>
        <dl>
          <dt>{t("opt.punctuation")}</dt><dd id="cur-punct">{punctuation ? t("short." + punctuation) : "—"}</dd>
          <dt>{t("opt.itn")}</dt><dd id="cur-itn">{itn ? t("short." + itn) : "—"}</dd>
        </dl>
        <a className="textlink" href="#models">{t("page.models")}</a>
      </section>
      <section className="metricsline">
        <Heading level={2}>{t("audio.median")}</Heading>
        <Paragraph id="cur-median">{timings.length ? t("audio.sample", { value: median.toFixed(2), count: timings.length }) : t("audio.noMetrics")}</Paragraph>
        <a className="textlink" href="#status">{t("audio.metrics")}</a>
      </section>
    </aside>
  );
}
