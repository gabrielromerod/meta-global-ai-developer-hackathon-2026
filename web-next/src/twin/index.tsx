import {
  Component,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import * as RadixTabs from "@radix-ui/react-tabs";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Camera, Eye, Layers3, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import {
  DoubleSide,
  PerspectiveCamera,
  Shape,
  Vector2,
  Vector3,
  type MeshBasicMaterial,
} from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { HouseViewProps } from "../contracts";
import {
  clampOrbit,
  coneFootprint,
  evidenceAtTime,
  framingFov,
  hatchSegments,
  layoutLabels,
  parseTwin,
  presetPose,
  type Ground,
  type SceneCamera,
  type TwinModel,
  type Vec2,
  type Vec3,
} from "./geometry";
import "./twin.css";

interface Palette {
  space: number;
  background: string;
  ground: string;
  house: string;
  roof: string;
  tree: string;
  accent: string;
  muted: string;
  warning: string;
  raised: string;
  line: number;
  lift: number;
  step: number;
  hatch: number;
  radius: number;
  opacity: number;
  activeOpacity: number;
  coverageOpacity: number;
  light: number;
  fov: number;
  minPolar: number;
  maxPolar: number;
  minDistance: number;
  maxDistance: number;
  damping: number;
  clearance: number;
  markerScale: number;
  duration: number;
}
interface AnnotationEntry {
  element: HTMLDivElement;
  position: Vec3;
  priority: number;
}
const AnnotationRegistry = createContext<Map<string, AnnotationEntry>>(
  new Map(),
);
function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement),
    color = (name: string) => css.getPropertyValue(name).trim();
  const numeric = (name: string) => parseFloat(color(name));
  return {
    space: numeric("--v-space-1"),
    background: color("--v-surface"),
    ground: color("--v-twin-ground"),
    house: color("--v-twin-house"),
    roof: color("--v-twin-roof"),
    tree: color("--v-twin-tree"),
    accent: color("--v-twin-cone"),
    muted: color("--v-muted"),
    warning: color("--v-warning"),
    raised: color("--v-raised"),
    line: numeric("--v-twin-path-width"),
    lift: numeric("--v-twin-ground-lift"),
    step: numeric("--v-twin-layer-step"),
    hatch: numeric("--v-twin-hatch-step"),
    radius: numeric("--v-twin-marker-radius"),
    opacity: numeric("--v-twin-cone-opacity"),
    activeOpacity: numeric("--v-twin-cone-active-opacity"),
    coverageOpacity: numeric("--v-twin-coverage-opacity"),
    light: numeric("--v-twin-light-intensity"),
    fov: numeric("--v-twin-camera-fov"),
    minPolar: numeric("--v-twin-orbit-min"),
    maxPolar: numeric("--v-twin-orbit-max"),
    minDistance: numeric("--v-twin-zoom-min"),
    maxDistance: numeric("--v-twin-zoom-max"),
    damping: numeric("--v-twin-damping"),
    clearance: numeric("--v-twin-camera-clearance"),
    markerScale: numeric("--v-twin-marker-scale"),
    duration: numeric("--v-motion-view") / 1000,
  };
}
function usePalette() {
  const [palette, setPalette] = useState(readPalette);
  useEffect(() => {
    const observer = new MutationObserver(() => setPalette(readPalette()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class", "style"],
    });
    return () => observer.disconnect();
  }, []);
  return palette;
}

class CanvasBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="twin-unavailable" role="status">
        <Eye aria-hidden="true" />
        <strong>3D view unavailable</strong>
        <span>
          This browser could not create the 3D canvas. Camera evidence remains
          available below.
        </span>
      </div>
    ) : (
      this.props.children
    );
  }
}

function GroundPolygon({
  points,
  y,
  color,
  opacity = 1,
}: {
  points: Vec2[];
  y: number;
  color: string;
  opacity?: number;
}) {
  const shape = useMemo(
    () => new Shape(points.map(([x, z]) => new Vector2(x, -z))),
    [points],
  );
  return (
    <mesh position={[0, y, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <shapeGeometry args={[shape]} />
      <meshBasicMaterial
        color={color}
        side={DoubleSide}
        transparent={opacity < 1}
        opacity={opacity}
        depthWrite={opacity >= 1}
      />
    </mesh>
  );
}
function AnnotationLayout() {
  const registry = useContext(AnnotationRegistry),
    { camera, size } = useThree(),
    last = useRef("");
  useFrame(() => {
    const projected = [...registry].map(([id, item]) => {
      const point = new Vector3(...item.position).project(camera);
      return {
        id,
        x: (point.x * 0.5 + 0.5) * size.width,
        y: (-point.y * 0.5 + 0.5) * size.height,
        width: item.element.offsetWidth,
        height: item.element.offsetHeight,
        priority: item.priority,
      };
    });
    const signature = JSON.stringify(
      projected.map((p) => [
        p.id,
        Math.round(p.x),
        Math.round(p.y),
        p.width,
        p.height,
      ]),
    );
    if (signature === last.current) return;
    last.current = signature;
    const margin = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue(
        "--v-space-1",
      ),
    );
    const placed = layoutLabels(
      projected,
      size.width,
      size.height - margin * 4,
      margin,
    );
    projected.forEach((item) => {
      const entry = registry.get(item.id),
        layout = placed.find((p) => p.id === item.id);
      if (!entry) return;
      entry.element.style.visibility = layout ? "visible" : "hidden";
      if (layout)
        entry.element.style.transform = `translate(${layout.x}px,${layout.y}px)`;
      const leader = entry.element.parentElement?.querySelector<SVGLineElement>(
        `[data-leader-id="${item.id}"]`,
      );
      if (leader) {
        leader.style.display = layout ? "" : "none";
        if (layout) {
          leader.setAttribute("x1", String(item.x));
          leader.setAttribute("y1", String(item.y));
          leader.setAttribute("x2", String(layout.x + item.width / 2));
          leader.setAttribute("y2", String(layout.y + item.height / 2));
        }
      }
    });
  });
  return null;
}
/** A single DOM overlay avoids the nested React roots used by drei Html. */
function HouseAnnotations({
  model,
  palette,
  evidence,
  activeCameraId,
  onCameraSelect,
  registry,
  hoveredRegion,
}: {
  model: TwinModel;
  palette: Palette;
  evidence: ReturnType<typeof evidenceAtTime>;
  activeCameraId?: string | null;
  onCameraSelect?: (id: string) => void;
  registry: Map<string, AnnotationEntry>;
  hoveredRegion: string | null;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const labels: {
    id: string;
    position: Vec3;
    priority: number;
    children: ReactNode;
  }[] = [];
  const region = (
    id: string,
    position: Vec3,
    children: ReactNode,
    priority = 1,
  ) =>
    labels.push({
      id,
      position,
      priority,
      children: <span className="twin-region-label">{children}</span>,
    });
  const house = model.boxes.find((box) => box.kind === "building");
  if (house) {
    region(
      "porch",
      [
        (house.min[0] + house.max[0]) / 2,
        palette.clearance,
        house.min[1] - palette.clearance,
      ],
      "Porch",
    );
    region(
      "passage",
      [
        model.ground.max[0] * 0.55,
        palette.clearance,
        (house.min[1] + house.max[1]) / 2,
      ],
      "Left passage",
    );
    region(
      "backyard",
      [0, palette.clearance, (house.max[1] + model.ground.max[1]) / 2],
      "Backyard",
    );
    region(
      "garden",
      [0, palette.clearance, (model.ground.min[1] + house.min[1]) / 2],
      "Front garden",
    );
  }
  model.boxes
    .filter((box) => box.kind === "tree_barrier")
    .forEach((box) =>
      region(
        `tree-${box.id}`,
        [
          (box.min[0] + box.max[0]) / 2,
          box.h + palette.clearance,
          (box.min[1] + box.max[1]) / 2,
        ],
        "Tree barrier",
      ),
    );
  model.cameras.forEach((camera) =>
    labels.push({
      id: `camera-${camera.id}`,
      position: [
        camera.position[0],
        camera.position[1] + palette.clearance,
        camera.position[2],
      ],
      priority: activeCameraId === camera.id ? 20 : 10,
      children: (
        <button
          type="button"
          className={`twin-pin ${activeCameraId === camera.id ? "is-selected" : ""}`}
          aria-label={`Select ${camera.name}`}
          aria-pressed={activeCameraId === camera.id}
          onClick={() => onCameraSelect?.(camera.id)}
          disabled={!onCameraSelect}
          title={`${camera.name} · ${camera.source_label}`}
        >
          <Camera aria-hidden="true" />
          <span>{camera.name}</span>
        </button>
      ),
    }),
  );
  model.blindRegions.forEach((region) => {
    const center = region.polygon_m.reduce<Vec2>(
      (sum, p) => [
        sum[0] + p[0] / region.polygon_m.length,
        sum[1] + p[1] / region.polygon_m.length,
      ],
      [0, 0],
    );
    labels.push({
      id: `blind-${region.id}`,
      position: [center[0], palette.clearance, center[1]],
      priority: 5,
      children: (
        <Tooltip.Provider delayDuration={0}>
          <Tooltip.Root
            open={hovered === region.id || hoveredRegion === region.id}
            onOpenChange={(open) => setHovered(open ? region.id : null)}
          >
            <Tooltip.Trigger asChild>
              <button
                type="button"
                className="twin-blind-label"
                aria-label={`Unobserved region: ${region.name}`}
              >
                <Eye aria-hidden="true" />
                <span>Unobserved</span>
              </button>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                className="twin-tooltip"
                sideOffset={palette.space}
                collisionPadding={palette.space}
              >
                {region.name}
                <Tooltip.Arrow />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        </Tooltip.Provider>
      ),
    });
  });
  evidence.gaps.forEach((gap) =>
    region(
      `gap-${gap.id}`,
      [
        (gap.from[0] + gap.to[0]) / 2,
        palette.clearance,
        (gap.from[1] + gap.to[1]) / 2,
      ],
      gap.label,
      3,
    ),
  );
  if (evidence.current)
    region(
      "current-estimate",
      [evidence.current.x, palette.clearance, evidence.current.z],
      evidence.current.label,
      4,
    );
  return (
    <div className="twin-label-layer">
      <svg className="twin-leaders" aria-hidden="true">
        {labels.map((label) => (
          <line key={label.id} data-leader-id={label.id} />
        ))}
      </svg>
      {labels.map((label) => (
        <div
          key={label.id}
          className="twin-annotation"
          data-label-id={label.id}
          ref={(element) => {
            if (element)
              registry.set(label.id, {
                element,
                position: label.position,
                priority: label.priority,
              });
            else registry.delete(label.id);
          }}
        >
          {label.children}
        </div>
      ))}
    </div>
  );
}

function SitePlan({ model, palette }: { model: TwinModel; palette: Palette }) {
  const { ground, boxes } = model;
  const groundPoints = useMemo<Vec2[]>(
    () => [
      [ground.min[0], ground.min[1]],
      [ground.max[0], ground.min[1]],
      [ground.max[0], ground.max[1]],
      [ground.min[0], ground.max[1]],
    ],
    [ground],
  );
  const house = boxes.find((b) => b.kind === "building");
  return (
    <group name="generic-public-massing">
      <GroundPolygon points={groundPoints} y={0} color={palette.ground} />
      <Line
        points={[...groundPoints, groundPoints[0]].map(([x, z]) => [
          x,
          palette.lift,
          z,
        ])}
        color={palette.roof}
        lineWidth={palette.line}
      />
      {boxes.map((box) => {
        const width = box.max[0] - box.min[0],
          depth = box.max[1] - box.min[1],
          x = (box.min[0] + box.max[0]) / 2,
          z = (box.min[1] + box.max[1]) / 2;
        return box.kind === "tree_barrier" ? (
          <group key={box.id} name="physical-tree-barrier">
            <mesh position={[x, box.h / 2, z]}>
              <boxGeometry args={[width, box.h, depth]} />
              <meshStandardMaterial color={palette.tree} roughness={1} />
            </mesh>
          </group>
        ) : (
          <group key={box.id}>
            <mesh position={[x, box.h / 2, z]}>
              <boxGeometry args={[width, box.h, depth]} />
              <meshStandardMaterial color={palette.house} roughness={1} />
            </mesh>
            <mesh position={[x, box.h + palette.step, z]}>
              <boxGeometry args={[width, palette.step, depth]} />
              <meshStandardMaterial color={palette.roof} roughness={1} />
            </mesh>
          </group>
        );
      })}
      {house && (
        <>
          <GroundPolygon
            points={[
              [house.min[0], house.min[1]],
              [house.max[0], house.min[1]],
              [house.max[0], ground.min[1] / 3],
              [house.min[0], ground.min[1] / 3],
            ]}
            y={palette.lift}
            color={palette.roof}
          />
        </>
      )}
      {model.coverage.map((region, i) => (
        <GroundPolygon
          key={`${region.camera_id}-${i}`}
          points={region.polygon_m}
          y={palette.lift + palette.step}
          color={palette.accent}
          opacity={palette.coverageOpacity}
        />
      ))}
    </group>
  );
}

function CameraCone({
  camera,
  model,
  palette,
  selected,
  pulse,
  reduced,
  onSelect,
}: {
  camera: SceneCamera;
  model: TwinModel;
  palette: Palette;
  selected: boolean;
  pulse: boolean;
  reduced: boolean;
  onSelect?: () => void;
}) {
  const material = useRef<MeshBasicMaterial>(null);
  const points = useMemo(
    () => coneFootprint(camera, model.boxes, model.ground),
    [camera, model],
  );
  const shape = useMemo(
    () => new Shape(points.map(([x, z]) => new Vector2(x, -z))),
    [points],
  );
  useFrame(({ clock }) => {
    if (material.current)
      material.current.opacity =
        pulse && !reduced
          ? palette.opacity +
            (palette.activeOpacity - palette.opacity) *
              (0.5 + 0.5 * Math.sin(clock.elapsedTime * Math.PI * 2))
          : selected || pulse
            ? palette.activeOpacity
            : palette.opacity;
  });
  return (
    <group name={`camera-${camera.id}`}>
      <mesh
        position={[0, palette.lift + palette.step * 2, 0]}
        rotation={[-Math.PI / 2, 0, 0]}
        onClick={(e) => {
          e.stopPropagation();
          onSelect?.();
        }}
      >
        <shapeGeometry args={[shape]} />
        <meshBasicMaterial
          ref={material}
          color={palette.accent}
          transparent
          opacity={palette.opacity}
          side={DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <mesh
        position={camera.position}
        onClick={(e) => {
          e.stopPropagation();
          onSelect?.();
        }}
      >
        <sphereGeometry args={[palette.radius, 16, 12]} />
        <meshBasicMaterial
          color={selected ? palette.warning : palette.accent}
        />
      </mesh>
    </group>
  );
}

function BlindRegions({
  model,
  palette,
  onHover,
}: {
  model: TwinModel;
  palette: Palette;
  onHover: (id: string | null) => void;
}) {
  return (
    <group name="blind-regions">
      {model.blindRegions.map((region) => {
        const lines = hatchSegments(region.polygon_m, palette.hatch);
        return (
          <group
            key={region.id}
            onPointerOver={(e) => {
              e.stopPropagation();
              onHover(region.id);
            }}
            onPointerOut={() => onHover(null)}
          >
            <GroundPolygon
              points={region.polygon_m}
              y={palette.lift + palette.step * 3}
              color={palette.muted}
              opacity={palette.opacity}
            />
            {lines.map((line, i) => (
              <Line
                key={i}
                points={line.map(([x, z]) => [
                  x,
                  palette.lift + palette.step * 4,
                  z,
                ])}
                color={palette.muted}
                lineWidth={palette.line}
              />
            ))}
          </group>
        );
      })}
    </group>
  );
}

function Evidence({
  data,
  time,
  palette,
}: {
  data: Record<string, unknown> | undefined;
  time: number;
  palette: Palette;
}) {
  const evidence = useMemo(() => evidenceAtTime(data, time), [data, time]);
  const current = evidence.current;
  return (
    <group name="observed-evidence">
      {evidence.paths.map((path, i) => (
        <Line
          key={i}
          points={path.map(([x, z]) => [x, palette.lift + palette.step * 5, z])}
          color={palette.warning}
          lineWidth={palette.line}
        />
      ))}
      {evidence.positions
        .filter((_, i) => i % 4 === 0)
        .map((p, i) => (
          <mesh
            key={i}
            position={[p.x, palette.lift + palette.step * 5, p.z]}
            rotation={[-Math.PI / 2, 0, 0]}
          >
            <ringGeometry
              args={[
                Math.max(palette.radius, p.r95 - palette.step),
                Math.max(palette.radius + palette.step, p.r95),
                32,
              ]}
            />
            <meshBasicMaterial
              color={palette.warning}
              transparent
              opacity={palette.opacity}
              side={DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ))}
      {evidence.gaps.map((gap) => (
        <group key={gap.id}>
          <Line
            points={[
              [gap.from[0], palette.lift + palette.step * 6, gap.from[1]],
              [gap.to[0], palette.lift + palette.step * 6, gap.to[1]],
            ]}
            color={palette.muted}
            lineWidth={palette.line}
            dashed
            dashSize={palette.radius}
            gapSize={palette.radius * 2}
          />
        </group>
      ))}
      {current && (
        <group
          position={[current.x, palette.lift + palette.step * 7, current.z]}
        >
          <mesh rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry
              args={[
                Math.max(palette.radius, current.r95 - palette.step),
                Math.max(palette.radius + palette.step, current.r95),
                48,
              ]}
            />
            <meshBasicMaterial color={palette.warning} side={DoubleSide} />
          </mesh>
          <mesh position={[0, palette.radius, 0]}>
            <sphereGeometry args={[palette.radius, 16, 12]} />
            <meshBasicMaterial color={palette.warning} />
          </mesh>
        </group>
      )}
    </group>
  );
}

function BoundedControls({
  ground,
  palette,
  preset,
  zoom,
  reduced,
  onState,
}: {
  ground: Ground;
  palette: Palette;
  preset: string;
  zoom: { factor: number; serial: number };
  reduced: boolean;
  onState: (position: Vec3, target: Vec3) => void;
}) {
  const controls = useRef<OrbitControlsImpl>(null),
    { camera, size } = useThree();
  useEffect(() => {
    if (camera instanceof PerspectiveCamera) {
      camera.fov = framingFov(palette.fov, size.width / size.height);
      camera.updateProjectionMatrix();
    }
  }, [camera, palette.fov, size.width, size.height]);
  const transition = useRef<{ position: Vector3; target: Vector3 } | null>(
    null,
  );
  useEffect(() => {
    const pose = presetPose(preset.split(":")[0], ground);
    transition.current = {
      position: new Vector3(...pose.position),
      target: new Vector3(...pose.target),
    };
  }, [preset, ground]);
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    transition.current = null;
    camera.position.sub(c.target).multiplyScalar(zoom.factor).add(c.target);
    c.update();
  }, [zoom.serial]);
  useFrame((_, delta) => {
    const c = controls.current;
    if (!c) return;
    if (transition.current) {
      const alpha =
        reduced || palette.duration === 0
          ? 1
          : 1 - Math.exp((-delta * 6) / palette.duration);
      camera.position.lerp(transition.current.position, alpha);
      c.target.lerp(transition.current.target, alpha);
      if (camera.position.distanceTo(transition.current.position) < 0.01) {
        camera.position.copy(transition.current.position);
        c.target.copy(transition.current.target);
        transition.current = null;
      }
    }
    const pose = clampOrbit(
      {
        position: camera.position.toArray() as Vec3,
        target: c.target.toArray() as Vec3,
      },
      ground,
      palette.minDistance,
      palette.maxDistance,
      palette.clearance,
    );
    camera.position.fromArray(pose.position);
    c.target.fromArray(pose.target);
    c.update();
    onState(pose.position, pose.target);
  });
  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableDamping={!reduced}
      dampingFactor={palette.damping}
      minPolarAngle={palette.minPolar}
      maxPolarAngle={palette.maxPolar}
      minDistance={palette.minDistance}
      maxDistance={palette.maxDistance}
      screenSpacePanning={false}
      onStart={() => {
        transition.current = null;
      }}
    />
  );
}

export function HouseView({
  twin,
  positions,
  time = 0,
  activeCameraId,
  onCameraSelect,
  preset: controlledPreset,
}: HouseViewProps) {
  const model = useMemo(() => parseTwin(twin), [twin]),
    palette = usePalette(),
    reduced = Boolean(useReducedMotion());
  const [preset, setPreset] = useState("front"),
    [reset, setReset] = useState(0),
    [zoom, setZoom] = useState({ factor: 1, serial: 0 }),
    [showCoverage, setShowCoverage] = useState(true);
  const [hoveredRegion, setHoveredRegion] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null!),
    registry = useRef(new Map<string, AnnotationEntry>()),
    evidence = useMemo(
      () => evidenceAtTime(positions, time),
      [positions, time],
    );
  const actualPreset = controlledPreset ?? preset;
  const activeCamera = model.cameras.find((c) => c.id === activeCameraId);
  const pose = presetPose("front", model.ground);
  return (
    <section
      className="house-view"
      aria-label="Property camera view"
      data-testid="house-view"
    >
      <div className="twin-toolbar">
        <RadixTabs.Root value={actualPreset} onValueChange={setPreset}>
          <RadixTabs.List
            aria-label="House view presets"
            className="twin-presets"
          >
            {[
              ["front", "Front"],
              ["left", "Left passage"],
              ["backyard", "Backyard"],
              ["top", "Top-down"],
            ].map(([id, label]) => (
              <RadixTabs.Trigger key={id} value={id} aria-label={label}>
                <span className="twin-preset-full">{label}</span>
                <span className="twin-preset-compact" aria-hidden="true">
                  {id === "left" ? "Passage" : id === "top" ? "Top" : label}
                </span>
              </RadixTabs.Trigger>
            ))}
          </RadixTabs.List>
        </RadixTabs.Root>
        <div className="twin-tools">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                className="twin-camera-menu"
                aria-label="Select camera"
                title="Select camera"
                disabled={!onCameraSelect}
              >
                <Camera aria-hidden="true" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                className="twin-camera-dropdown"
                sideOffset={palette.space}
                collisionPadding={palette.space}
                align="end"
              >
                <DropdownMenu.Label>Configured cameras</DropdownMenu.Label>
                <DropdownMenu.RadioGroup
                  value={activeCameraId ?? ""}
                  onValueChange={(id) => onCameraSelect?.(id)}
                >
                  {model.cameras.map((camera) => (
                    <DropdownMenu.RadioItem key={camera.id} value={camera.id}>
                      <Camera aria-hidden="true" />
                      <span>{camera.name}</span>
                      <span className="twin-menu-status">
                        {camera.source_label}
                      </span>
                    </DropdownMenu.RadioItem>
                  ))}
                </DropdownMenu.RadioGroup>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
          <button
            type="button"
            aria-label="Toggle camera coverage"
            title="Camera coverage"
            aria-pressed={showCoverage}
            onClick={() => setShowCoverage((v) => !v)}
          >
            <Layers3 aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            title="Zoom in"
            onClick={() =>
              setZoom((v) => ({ factor: 0.8, serial: v.serial + 1 }))
            }
          >
            <ZoomIn aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label="Zoom out"
            title="Zoom out"
            onClick={() =>
              setZoom((v) => ({ factor: 1.25, serial: v.serial + 1 }))
            }
          >
            <ZoomOut aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label="Reset view"
            title="Reset view"
            onClick={() => {
              setPreset("front");
              setReset((v) => v + 1);
            }}
          >
            <RotateCcw aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="twin-canvas" ref={container} data-testid="twin-canvas">
        <AnnotationRegistry.Provider value={registry.current}>
          <CanvasBoundary>
            <Canvas
              camera={{
                position: pose.position,
                fov: palette.fov,
                near: 0.1,
                far: 300,
              }}
              dpr={[1, 2]}
              gl={{ antialias: true, alpha: false }}
              fallback={
                <div className="twin-unavailable" role="status">
                  3D view unavailable. WebGL is required to show this view.
                </div>
              }
              onCreated={({ gl }) => {
                gl.domElement.setAttribute(
                  "aria-label",
                  "3D house view. Drag to orbit; use the view and zoom buttons for keyboard control.",
                );
                gl.domElement.setAttribute("role", "img");
                if (container.current)
                  container.current.dataset.webgl = "ready";
              }}
            >
              <color attach="background" args={[palette.background]} />
              <ambientLight intensity={palette.light} />
              <directionalLight
                position={[-8, 20, -6]}
                intensity={palette.light}
              />
              <SitePlan model={model} palette={palette} />
              <BlindRegions
                model={model}
                palette={palette}
                onHover={setHoveredRegion}
              />
              {model.cameras.map((camera) => (
                <CameraCone
                  key={camera.id}
                  camera={camera}
                  model={model}
                  palette={{
                    ...palette,
                    opacity: showCoverage ? palette.opacity : 0,
                    activeOpacity: showCoverage ? palette.activeOpacity : 0,
                  }}
                  selected={activeCameraId === camera.id}
                  pulse={evidence.pulseCameras.includes(camera.id)}
                  reduced={reduced}
                  onSelect={
                    onCameraSelect ? () => onCameraSelect(camera.id) : undefined
                  }
                />
              ))}
              <Evidence data={positions} time={time} palette={palette} />
              <BoundedControls
                ground={model.ground}
                palette={palette}
                preset={`${actualPreset}:${reset}`}
                zoom={zoom}
                reduced={reduced}
                onState={(position, target) => {
                  if (container.current) {
                    container.current.dataset.cameraY = String(position[1]);
                    container.current.dataset.orbitDistance = String(
                      Math.hypot(...position.map((n, i) => n - target[i])),
                    );
                    container.current.dataset.target = target.join(",");
                  }
                }}
              />
              <AnnotationLayout />
            </Canvas>
          </CanvasBoundary>
        </AnnotationRegistry.Provider>

        <HouseAnnotations
          model={model}
          palette={palette}
          evidence={evidence}
          activeCameraId={activeCameraId}
          onCameraSelect={onCameraSelect}
          registry={registry.current}
          hoveredRegion={hoveredRegion}
        />
        <span className="twin-map-note">
          Stylized property · approximate locations
        </span>
      </div>
      <div className="twin-camera-list" aria-label="Select a camera">
        {model.cameras.map((camera) => (
          <button
            type="button"
            key={camera.id}
            aria-pressed={activeCameraId === camera.id}
            disabled={!onCameraSelect}
            onClick={() => onCameraSelect?.(camera.id)}
          >
            <Camera aria-hidden="true" />
            {camera.name}
          </button>
        ))}
      </div>
      <div className="twin-footer">
        <span>
          <span className="twin-key twin-key-camera" />
          Camera coverage · nominal
        </span>
        <span>
          <span className="twin-key twin-key-evidence" />
          Observed path
        </span>
        <span>
          <span className="twin-key twin-key-gap" />
          Unobserved
        </span>
        <span className="twin-selection" role="status">
          {activeCamera
            ? `${activeCamera.name} · ${activeCamera.source_label}`
            : model.cameras.length
              ? "Select a camera to open its evidence"
              : "No cameras configured"}
        </span>
      </div>
      {evidence.gapLabels.length > 0 && (
        <p className="twin-gap-summary">
          {evidence.gapLabels.join(" · ")}. No position is inferred inside a
          gap.
        </p>
      )}
    </section>
  );
}
