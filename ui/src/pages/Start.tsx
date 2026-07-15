import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  FileJson,
  Network,
  PencilRuler,
  Radio,
  Sparkles,
} from "lucide-react";
import { useI18n } from "../i18n";
import { Button } from "../components/ui";
import { markOnboarded } from "../onboarding";

interface Step {
  key: string;
  title: string;
  subtitle: string;
  body: ReactNode;
}

export function Start() {
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const steps = useSteps();
  const last = steps.length - 1;

  function go(to: number) {
    setStep(Math.max(0, Math.min(to, last)));
  }
  function finish() {
    markOnboarded();
    navigate("/");
  }

  // Left/right arrows navigate steps.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target;
      if (el instanceof HTMLElement && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") go(step + 1);
      if (e.key === "ArrowLeft") go(step - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const current = steps[step];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-8 py-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent-soft text-accent">
              <Sparkles size={20} />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight text-fg">
                {t("Aan de slag", "Get started")}
              </h1>
              <p className="text-sm text-fg-muted">
                {t(
                  "Snelstart — leer hoe je met UNS Design Studio een fabriek modelleert en live data publiceert",
                  "Quick start — learn how UNS Design Studio models a plant and publishes live data",
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex overflow-hidden rounded-lg border border-border text-xs font-medium">
              <button
                onClick={() => setLang("nl")}
                className={lang === "nl" ? "bg-accent px-2.5 py-1 text-accent-fg" : "px-2.5 py-1 text-fg-muted hover:bg-surface-2"}
              >
                NL
              </button>
              <button
                onClick={() => setLang("en")}
                className={lang === "en" ? "bg-accent px-2.5 py-1 text-accent-fg" : "px-2.5 py-1 text-fg-muted hover:bg-surface-2"}
              >
                EN
              </button>
            </div>
            <Button variant="ghost" onClick={finish}>
              {t("Sla over", "Skip")}
            </Button>
          </div>
        </div>

        {/* step indicator */}
        <ol className="flex flex-wrap items-center gap-2">
          {steps.map((s, i) => {
            const state = i === step ? "current" : i < step ? "done" : "todo";
            return (
              <li key={s.key} className="flex items-center gap-2">
                <button
                  onClick={() => go(i)}
                  title={s.title}
                  className={
                    "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-tokens " +
                    (state === "current"
                      ? "bg-accent text-accent-fg shadow-card"
                      : state === "done"
                        ? "bg-accent-soft text-accent hover:bg-accent-soft/80"
                        : "bg-surface-2 text-fg-muted hover:text-fg")
                  }
                >
                  {i + 1}
                </button>
                {i < steps.length - 1 && (
                  <span className={"h-px w-4 " + (i < step ? "bg-accent/50" : "bg-border")} />
                )}
              </li>
            );
          })}
        </ol>

        {/* content card */}
        <div key={current.key} className="rise-in rounded-2xl border border-border bg-surface p-6 shadow-card">
          <p className="text-[11px] font-medium uppercase tracking-wide text-accent">
            {t("Stap", "Step")} {step + 1} {t("van", "of")} {steps.length}
          </p>
          <h2 className="mt-1 text-lg font-semibold text-fg">{current.title}</h2>
          <p className="text-sm text-fg-faint">{current.subtitle}</p>
          <div className="mt-4 flex flex-col gap-4 text-sm leading-relaxed text-fg-muted">
            {current.body}
          </div>
        </div>

        {/* controls */}
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={() => go(step - 1)} disabled={step === 0}>
            <span className="inline-flex items-center gap-1.5">
              <ArrowLeft size={15} />
              {t("Vorige", "Previous")}
            </span>
          </Button>
          {step === last ? (
            <Button onClick={finish}>
              <span className="inline-flex items-center gap-1.5">
                <Network size={15} />
                {t("Naar de UNS Hub", "Go to the UNS Hub")}
              </span>
            </Button>
          ) : (
            <Button onClick={() => go(step + 1)}>
              <span className="inline-flex items-center gap-1.5">
                {t("Volgende", "Next")}
                <ArrowRight size={15} />
              </span>
            </Button>
          )}
        </div>

        <p className="text-center text-[11px] text-fg-faint">
          {t(
            "Tip: navigeer met de ← / → pijltjestoetsen. Deze wizard blijft bereikbaar via het menu.",
            "Tip: navigate with the ← / → arrow keys. This wizard stays available from the menu.",
          )}
        </p>
      </div>
    </div>
  );
}

// ── step content ──

function useSteps(): Step[] {
  const { lang } = useI18n();
  const en = lang === "en";
  const heading = (nl: string, enT: string) => ({ title: en ? enT : nl, subtitle: en ? nl : enT });
  return [
    {
      key: "what",
      ...heading("Wat is UNS Design Studio?", "What is UNS Design Studio?"),
      body: (
        <>
          <div className="my-1">
            <PipelineSketch />
          </div>
          {en ? (
            <>
              <p>
                UNS Design Studio is a <strong>self-contained Unified Namespace simulator</strong>. You
                model an <strong>ISA-95 enterprise</strong>, generate realistic plant data, and publish it
                over <strong>OPC-UA, MQTT and NATS</strong> — all <strong>without a single real machine</strong>.
              </p>
              <p>
                It drives this demo's live UNS data: the sites, assets, tags and payloads you design here
                are what every other app on the bus actually sees.
              </p>
              <p>
                This wizard is a <strong>guided tour</strong> of the studio. Take it once; everything here
                stays reachable any time from the sidebar.
              </p>
            </>
          ) : (
            <>
              <p>
                UNS Design Studio is een <strong>op zichzelf staande Unified Namespace-simulator</strong>. Je
                modelleert een <strong>ISA-95-onderneming</strong>, genereert realistische fabrieksdata en
                publiceert die over <strong>OPC-UA, MQTT en NATS</strong> — helemaal{" "}
                <strong>zonder één echte machine</strong>.
              </p>
              <p>
                Het voedt de live UNS-data van deze demo: de sites, assets, tags en payloads die je hier
                ontwerpt zijn wat elke andere app op de bus daadwerkelijk ziet.
              </p>
              <p>
                Deze wizard is een <strong>rondleiding</strong> langs de studio. Doorloop hem één keer; alles
                hier blijft altijd bereikbaar via het menu.
              </p>
            </>
          )}
        </>
      ),
    },
    {
      key: "designer",
      ...heading("Modelleer je onderneming", "Model your enterprise"),
      body: (
        <>
          {en ? (
            <>
              <p>
                The <strong>UNS Designer</strong> is where it begins. Build the{" "}
                <strong>ISA-95 tree</strong> visually — enterprise, sites, areas, lines and assets — and it
                is saved as the <code>uns_config.json</code> that backs the whole simulator.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  <strong>Drag &amp; drop</strong> the enterprise hierarchy into shape.
                </FeatureLi>
                <FeatureLi>
                  Attach <strong>tags and recipes</strong> to each asset — the signals that will flow.
                </FeatureLi>
                <FeatureLi>
                  Import <strong>templates</strong> from the asset library to start fast.
                </FeatureLi>
              </ul>
              <p>
                <Link to="/uns" className="font-medium text-accent hover:underline">
                  Open the UNS Designer →
                </Link>
              </p>
            </>
          ) : (
            <>
              <p>
                De <strong>UNS Designer</strong> is waar het begint. Bouw de{" "}
                <strong>ISA-95-boom</strong> visueel op — onderneming, sites, gebieden, lijnen en assets — en
                die wordt opgeslagen als de <code>uns_config.json</code> waarop de hele simulator draait.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  <strong>Sleep</strong> de ondernemingshiërarchie in vorm.
                </FeatureLi>
                <FeatureLi>
                  Koppel <strong>tags en recepten</strong> aan elke asset — de signalen die gaan stromen.
                </FeatureLi>
                <FeatureLi>
                  Importeer <strong>sjablonen</strong> uit de asset-bibliotheek om snel te starten.
                </FeatureLi>
              </ul>
              <p>
                <Link to="/uns" className="font-medium text-accent hover:underline">
                  Open de UNS Designer →
                </Link>
              </p>
            </>
          )}
        </>
      ),
    },
    {
      key: "schemas",
      ...heading("Ontwerp je payloads", "Design your payloads"),
      body: (
        <>
          {en ? (
            <>
              <p>
                <strong>Payload Schemas</strong> decides the <em>shape</em> of every message the simulator
                publishes. Choose a flat value, a <strong>Sparkplug-style</strong> envelope, or your own
                JSON template — with timestamps, quality and metadata where you want them.
              </p>
              <p>
                One schema, applied across the tree, keeps every topic consistent — exactly the contract a
                real UNS consumer would expect to parse.
              </p>
              <p>
                <Link to="/payload-schemas" className="font-medium text-accent hover:underline">
                  Open Payload Schemas →
                </Link>
              </p>
            </>
          ) : (
            <>
              <p>
                <strong>Payload Schemas</strong> bepaalt de <em>vorm</em> van elk bericht dat de simulator
                publiceert. Kies een platte waarde, een <strong>Sparkplug-achtige</strong> envelop of je
                eigen JSON-sjabloon — met tijdstempels, kwaliteit en metadata waar jij ze wilt.
              </p>
              <p>
                Eén schema, toegepast op de hele boom, houdt elke topic consistent — precies het contract dat
                een echte UNS-consument verwacht te parsen.
              </p>
              <p>
                <Link to="/payload-schemas" className="font-medium text-accent hover:underline">
                  Open Payload Schemas →
                </Link>
              </p>
            </>
          )}
        </>
      ),
    },
    {
      key: "live",
      ...heading("Zie het live publiceren", "Watch it publish live"),
      body: (
        <>
          {en ? (
            <>
              <p>
                Start the server, plants and bridge, and the <strong>Live UNS View</strong> shows the topic
                tree filling with real values — the same stream flowing over{" "}
                <strong>MQTT and NATS</strong> to every subscriber.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  The full <strong>topic hierarchy</strong>, updating in real time in the browser.
                </FeatureLi>
                <FeatureLi>
                  Live values per tag — proof the bridge is actually publishing.
                </FeatureLi>
              </ul>
              <p>
                <Link to="/live" className="font-medium text-accent hover:underline">
                  Open the Live UNS View →
                </Link>
              </p>
            </>
          ) : (
            <>
              <p>
                Start de server, plants en bridge, en de <strong>Live UNS View</strong> toont de topic-boom
                die zich vult met echte waarden — dezelfde stroom die over{" "}
                <strong>MQTT en NATS</strong> naar elke abonnee gaat.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  De volledige <strong>topic-hiërarchie</strong>, live bijgewerkt in de browser.
                </FeatureLi>
                <FeatureLi>
                  Live waarden per tag — bewijs dat de bridge daadwerkelijk publiceert.
                </FeatureLi>
              </ul>
              <p>
                <Link to="/live" className="font-medium text-accent hover:underline">
                  Open de Live UNS View →
                </Link>
              </p>
            </>
          )}
        </>
      ),
    },
    {
      key: "explore",
      ...heading("Verken de hub en visualisaties", "Explore the hub and visualizations"),
      body: (
        <>
          {en ? (
            <>
              <p>
                The <strong>UNS Hub</strong> — the home screen — draws your namespace as a hub-and-spoke map:
                the enterprise at the centre, every site and asset radiating out, edges pulsing as topics
                publish. <strong>Visualization</strong> turns those same signals into dashboards, gauges and
                trends.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  <strong>UNS Hub</strong> — the live spoke-map of the whole namespace.
                </FeatureLi>
                <FeatureLi>
                  <strong>Visualization</strong> — dashboards over the generated plant data.
                </FeatureLi>
              </ul>
              <p className="flex flex-wrap gap-4">
                <Link to="/" className="font-medium text-accent hover:underline">
                  Open the UNS Hub →
                </Link>
                <Link to="/viz" className="font-medium text-accent hover:underline">
                  Open Visualization →
                </Link>
              </p>
            </>
          ) : (
            <>
              <p>
                De <strong>UNS Hub</strong> — het startscherm — tekent je namespace als een hub-en-spaak-kaart:
                de onderneming in het midden, elke site en asset eromheen, verbindingen die pulseren zodra
                topics publiceren. <strong>Visualization</strong> maakt van diezelfde signalen dashboards,
                meters en trends.
              </p>
              <ul className="flex flex-col gap-1.5 pl-1">
                <FeatureLi>
                  <strong>UNS Hub</strong> — de live spaak-kaart van de hele namespace.
                </FeatureLi>
                <FeatureLi>
                  <strong>Visualization</strong> — dashboards over de gegenereerde fabrieksdata.
                </FeatureLi>
              </ul>
              <p className="flex flex-wrap gap-4">
                <Link to="/" className="font-medium text-accent hover:underline">
                  Open de UNS Hub →
                </Link>
                <Link to="/viz" className="font-medium text-accent hover:underline">
                  Open Visualization →
                </Link>
              </p>
            </>
          )}
        </>
      ),
    },
    {
      key: "manual",
      ...heading("Verdieping en volgende stappen", "Go deeper and next steps"),
      body: (
        <>
          {en ? (
            <>
              <p>
                The <strong>User Manual</strong> is the full reference — protocols and ports, the bridge and
                broker, OPC-UA details, and how each screen fits together. Reach for it whenever a setting
                needs explaining.
              </p>
              <p>
                That's the loop: <strong>model</strong> the enterprise, <strong>shape</strong> the payloads,{" "}
                <strong>publish</strong> live, <strong>explore</strong> the result.
              </p>
              <p>
                <Link to="/manual" className="font-medium text-accent hover:underline">
                  Open the User Manual →
                </Link>
              </p>
              <p className="rounded-lg border border-border bg-bg px-3 py-2 text-xs text-fg-muted">
                Ready? <strong>Go to the UNS Hub</strong> for the live map — or reopen this tour any time from{" "}
                <strong>Quick start</strong> in the sidebar.
              </p>
            </>
          ) : (
            <>
              <p>
                De <strong>User Manual</strong> is het volledige naslagwerk — protocollen en poorten, de
                bridge en broker, OPC-UA-details, en hoe elk scherm samenhangt. Grijp ernaar zodra een
                instelling uitleg nodig heeft.
              </p>
              <p>
                Dat is de cirkel: <strong>modelleer</strong> de onderneming, <strong>vorm</strong> de
                payloads, <strong>publiceer</strong> live, <strong>verken</strong> het resultaat.
              </p>
              <p>
                <Link to="/manual" className="font-medium text-accent hover:underline">
                  Open de User Manual →
                </Link>
              </p>
              <p className="rounded-lg border border-border bg-bg px-3 py-2 text-xs text-fg-muted">
                Klaar? <strong>Naar de UNS Hub</strong> voor de live kaart — of heropen deze rondleiding altijd
                via <strong>Quick start</strong> in het menu.
              </p>
            </>
          )}
        </>
      ),
    },
  ];
}

function FeatureLi({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
      <span>{children}</span>
    </li>
  );
}

// ── inline illustration (family accent colours, both themes) ──

// The studio pipeline: model an ISA-95 enterprise, generate plant data, publish
// it over OPC-UA / MQTT / NATS — no real machines. Static, theme-aware SVG
// (family CSS variables).
function PipelineSketch() {
  const stages: Array<{ icon: ReactNode; label: string }> = [
    { icon: <PencilRuler size={16} />, label: "Model" },
    { icon: <FileJson size={16} />, label: "Payload" },
    { icon: <Radio size={16} />, label: "Publish" },
  ];
  const protocols = ["OPC-UA", "MQTT", "NATS"];
  const cx: number[] = [70, 190, 310];
  const cy = 70;
  return (
    <div className="rounded-xl border border-border bg-bg p-3">
      <svg viewBox="0 0 380 170" className="mx-auto w-full max-w-md" role="img" aria-label="Model, payload en publiceren over OPC-UA, MQTT en NATS">
        {/* connectors between the three stages */}
        <g stroke="var(--fg-faint)" strokeWidth="1.6" strokeLinecap="round" opacity="0.55" fill="none">
          <line x1={cx[0] + 24} y1={cy} x2={cx[1] - 24} y2={cy} />
          <line x1={cx[1] + 24} y1={cy} x2={cx[2] - 24} y2={cy} />
        </g>
        {stages.map((s, i) => (
          <g key={s.label}>
            <circle
              cx={cx[i]}
              cy={cy}
              r="22"
              fill={i === 2 ? "var(--accent-soft)" : "var(--surface)"}
              stroke={i === 2 ? "var(--accent)" : "var(--border)"}
              strokeWidth="1.5"
            />
            <foreignObject x={cx[i] - 10} y={cy - 10} width="20" height="20">
              <div style={{ color: i === 2 ? "var(--accent)" : "var(--fg-muted)", display: "grid", placeItems: "center" }}>
                {s.icon}
              </div>
            </foreignObject>
            <text
              x={cx[i]}
              y={cy - 32}
              textAnchor="middle"
              fontSize="10.5"
              fontFamily="var(--font-sans)"
              fontWeight="600"
              fill="var(--fg-muted)"
            >
              {s.label}
            </text>
          </g>
        ))}
        {/* protocol fan-out from Publish */}
        <g stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" opacity="0.5" fill="none">
          {protocols.map((_, i) => (
            <line key={i} x1={cx[2]} y1={cy + 22} x2={cx[2] - 40 + i * 40} y2={cy + 44} />
          ))}
        </g>
        {protocols.map((p, i) => (
          <text
            key={p}
            x={cx[2] - 40 + i * 40}
            y={cy + 60}
            textAnchor="middle"
            fontSize="9.5"
            fontFamily="var(--font-mono)"
            fontWeight="600"
            fill="var(--accent)"
          >
            {p}
          </text>
        ))}
        <text
          x="190"
          y="150"
          textAnchor="middle"
          fontSize="9.5"
          fontFamily="var(--font-sans)"
          fill="var(--fg-faint)"
        >
          <tspan>ISA-95 model → plant data → live bus — no real machines</tspan>
        </text>
      </svg>
    </div>
  );
}
