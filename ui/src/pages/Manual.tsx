import { Link } from "react-router-dom";
import {
  BookOpen,
  Play,
  LayoutDashboard,
  Network,
  ScrollText,
  Cable,
  Radio,
  Wrench,
} from "lucide-react";
import { Page, Card } from "../components/ui";

function Steps({ items }: { items: string[] }) {
  return (
    <ol className="list-decimal space-y-1.5 pl-5 text-sm text-fg-muted marker:text-fg-faint">
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ol>
  );
}
function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1.5 pl-5 text-sm text-fg-muted marker:text-fg-faint">
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

export function Manual() {
  return (
    <Page
      title="User Manual"
      subtitle="Build, simulate, inspect and publish a virtual Unified Namespace."
    >
      <Card
        title="What is UNS Design Studio?"
        icon={<BookOpen size={16} />}
        footer={
          <div className="flex flex-wrap gap-2">
            <Link to="/" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover">
              Open UNS Simulation Publisher
            </Link>
            <Link to="/uns" className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-surface-2">
              Design UNS
            </Link>
            <Link to="/live" className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-surface-2">
              Live View
            </Link>
          </div>
        }
      >
        <p className="text-sm text-fg-muted">
          A local industrial simulator for designing a Unified Namespace tree, generating OPC-UA
          data, injecting anomalies, and bridging live values to MQTT or NATS. Everything is
          auto-discovered from your UNS model — nothing is hardcoded.
        </p>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card title="1 · Start the simulator" icon={<Play size={16} />}>
          <Steps
            items={[
              "Open the UNS Simulation Publisher.",
              "Start the OPC-UA server from the toolbar.",
              "Wait until OPC-UA and Bridge show green.",
              "Use the main Simulation switch to run or pause all plants.",
            ]}
          />
          <p className="mt-3 rounded-lg bg-surface-2 px-3 py-2 text-xs text-fg-muted">
            Plants can't run while the OPC-UA server is stopped — start the server first.
          </p>
        </Card>

        <Card title="2 · Read the hub" icon={<LayoutDashboard size={16} />}>
          <Bullets
            items={[
              "The UNS sits at the core; business units and sites fan out as spokes.",
              "Click a node to expand its ISA-95 sublevels along the same spoke.",
              "Green nodes + flowing edges are live and publishing; grey dashed are offline.",
              "The Live UNS panel folds the current members into a topic tree.",
            ]}
          />
        </Card>

        <Card title="3 · Design the UNS" icon={<Network size={16} />}>
          <Bullets
            items={[
              "Open the Data Model Designer (UNS model) to edit enterprise, business units, sites, areas, work centers, work units and tags.",
              "Tags carry simulation profiles that make them discoverable for metrics and publishing.",
              "Saving rewrites the live UNS config and restarts the simulator components.",
            ]}
          />
        </Card>

        <Card title="4 · Recipes & schemas" icon={<ScrollText size={16} />}>
          <Bullets
            items={[
              "Add recipes at site level; pick the active recipe per plant.",
              "Add simulation profiles to tags for dashboard metrics and live publishing.",
              "Use Payload Schemas to shape the JSON published to downstream systems.",
            ]}
          />
        </Card>

        <Card title="5 · Bridge to MQTT / NATS" icon={<Cable size={16} />}>
          <Steps
            items={[
              "Open Settings → MQTT / NATS bridge.",
              "Choose the protocol, host, port, credentials, topic prefix and interval.",
              "Start the bridge from the hub toolbar.",
              "Watch the OPC/broker status and publish rate.",
            ]}
          />
        </Card>

        <Card title="6 · Live UNS View" icon={<Radio size={16} />}>
          <Bullets
            items={[
              "Inspect live broker traffic and the published topic structure.",
              "Start the bridge before expecting MQTT/NATS updates.",
              "Use the topic tree to verify the downstream namespace shape.",
            ]}
          />
        </Card>
      </div>

      <Card title="Troubleshooting" icon={<Wrench size={16} />}>
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            ["Plants won't start", "Start the OPC-UA server first and wait for the green status, then use the Simulation switch."],
            ["No broker messages", "Check the bridge config, start the bridge, and confirm the broker status says connected."],
            ["Metrics show dashes", "Confirm the plant is running, OPC is connected, and tags have simulation profiles."],
            ["Designer changes not visible", "Save in the Data Model Designer — the publisher reloads when the structure changes."],
          ].map(([h, b]) => (
            <div key={h}>
              <div className="text-sm font-semibold text-fg">{h}</div>
              <p className="mt-0.5 text-xs text-fg-muted">{b}</p>
            </div>
          ))}
        </div>
      </Card>
    </Page>
  );
}
