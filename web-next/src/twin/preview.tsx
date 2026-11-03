import { useState } from "react";
import { createRoot } from "react-dom/client";
import twin from "../fixtures/twin.json";
import positions from "../fixtures/positions.json";
import visits from "../fixtures/visits.json";
import { HouseView } from "./index";
import "../styles/tokens.css";
import "./preview.css";
function Preview() {
  const [camera, setCamera] = useState<string | null>(null),
    [time, setTime] = useState(15260),
    [theme, setTheme] = useState("dark");
  return (
    <main className="twin-preview">
      <header>
        <div>
          <h1>Property view</h1>
          <p>Demo data · authored synthetic ledger</p>
        </div>
        <button
          onClick={() => {
            const next = theme === "dark" ? "light" : "dark";
            setTheme(next);
            document.documentElement.dataset.theme = next;
          }}
        >
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
      </header>
      <div className="twin-preview-stage">
        <HouseView
          twin={twin}
          positions={{ ...positions, events: visits.visits.v_c.events }}
          time={time}
          activeCameraId={camera}
          onCameraSelect={setCamera}
        />
      </div>
      <footer>
        <label htmlFor="evidence-time">
          Recorded session time · {time.toFixed(1)} s
        </label>
        <input
          id="evidence-time"
          type="range"
          min={15186}
          max={15360}
          step={0.5}
          value={time}
          onChange={(event) => setTime(Number(event.target.value))}
        />
        <p>
          All cameras are disconnected. This view demonstrates generated
          evidence only.
        </p>
      </footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
