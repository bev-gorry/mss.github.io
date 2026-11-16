// Interactive point cloud viewer for the baseline comparison (three.js).
// The method tabs (index.js) call window.cloudViewer.show(key). Clouds are loaded on first use and cached.
// If WebGL or this module fails, the static render already in the page (#cloud-img) stays visible.
//
// Rendering:
//  - points are round discs sized in world units, so they grow when zooming in (detail, not blobs);
//  - Eye-Dome Lighting: a screen-space pass that darkens pixels lying behind their neighbours (from the depth
//    buffer), so the cloud reads as a surface with relief instead of a flat scatter of dots;
//  - cameras are wireframe frustums (apex + image rectangle), red as in the paper or coloured by session. They are
//    drawn after the shading pass so the thin lines keep their colour (they sit above the reef, so drawing them on
//    top rarely hides anything).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

const BASE = "./static/pointclouds/s01";
const POINT_WORLD_SIZE = 0.009;    // disc diameter in the normalised (unit radius) frame
const EDL_STRENGTH = 15;           // higher = darker relief shading
// Session colouring of the points: the image colour is first lightened towards white (LIFT), then mixed with the
// session colour (TINT). The paper figures use LIFT 0, TINT 0.4; underwater images are dark, so that reads heavy here.
const TINT = 0.6;
const LIFT = 0.0;
const EDL_RADIUS = 1.5;            // neighbour distance, in device pixels
// oblique side view, like the paper figure: misaligned sessions show up as separate layers
const START = new THREE.Vector3(0, -1.9, 0.6);

// sRGB 0-255 colours, passed through unchanged (no colour management), so they match the paper figures
const CAMERA_RED = [214, 39, 40];
const SESSION_COLOURS = [[106, 178, 212], [243, 201, 9], [227, 119, 194]];   // 2016, 2017, 2018
const NO_SESSION = [127, 127, 127];

const POINT_VERTEX = /* glsl */ `
  attribute vec3 imageRGB;       // original image colour (0-255)
  attribute float sessionId;     // 0-2: one session, 3: several sessions, 255: unknown
  uniform vec3 uSessionColours[4];
  uniform float uUseImage;
  uniform float uTint;
  uniform float uLift;
  uniform float uWorldSize;
  uniform float uViewportHeight;
  varying vec3 vColor;
  void main() {
    vec3 color = imageRGB / 255.0;
    vec3 session = uSessionColours[int(min(sessionId, 3.0))];
    vec3 tinted = mix(mix(color, vec3(1.0), uLift), session, uTint);
    vColor = uUseImage > 0.5 ? color : tinted;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    // world-space diameter -> pixels: focal length in pixels (P[1][1] * h / 2) over the depth
    gl_PointSize = clamp(uWorldSize * projectionMatrix[1][1] * 0.5 * uViewportHeight / -mv.z, 1.0, 24.0);
  }`;

const POINT_FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  void main() {
    if (length(gl_PointCoord - 0.5) > 0.5) discard;   // round disc with a hard edge
    gl_FragColor = vec4(vColor, 1.0);
  }`;

const EDL_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const EDL_FRAGMENT = /* glsl */ `
  uniform sampler2D tColor;
  uniform sampler2D tDepth;
  uniform vec2 uTexel;       // radius / resolution
  uniform float uNear;
  uniform float uFar;
  uniform float uStrength;
  varying vec2 vUv;

  float viewDepth(vec2 uv) {           // depth buffer value -> distance from the camera (perspective)
    float d = texture2D(tDepth, uv).x;
    return uNear * uFar / (uFar - d * (uFar - uNear));
  }
  bool isEmpty(vec2 uv) { return texture2D(tDepth, uv).x >= 1.0; }

  void main() {
    vec4 colour = texture2D(tColor, vUv);
    if (isEmpty(vUv)) { gl_FragColor = colour; return; }
    float logD = log2(viewDepth(vUv));
    float response = 0.0;
    // 8 neighbours on a ring; only neighbours that hit geometry count, so isolated points don't get dark halos
    for (int i = 0; i < 8; i++) {
      float a = float(i) * 0.785398;
      vec2 uv = vUv + vec2(cos(a), sin(a)) * uTexel;
      if (!isEmpty(uv)) response += max(0.0, logD - log2(viewDepth(uv)));
    }
    float shade = exp(-uStrength * response / 8.0);
    gl_FragColor = vec4(colour.rgb * mix(shade, 1.0, 0.1), 1.0);
  }`;

function rgb01(c) { return c.map((v) => v / 255); }

function createViewer(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;   // pass colours straight through
  const canvas = renderer.domElement;
  container.prepend(canvas);

  const scene = new THREE.Scene();          // points (shaded)
  scene.background = new THREE.Color(1, 1, 1);
  const cameraScene = new THREE.Scene();    // frustums (drawn on top, unshaded)
  const camera = new THREE.PerspectiveCamera(45, 4 / 3, 0.02, 20);
  camera.up.set(0, 0, 1);    // clouds are exported with the reef plane horizontal and +z up

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minDistance = 0.15;
  controls.maxDistance = 8;

  // Don't hijack page scrolling: wheel zoom only after clicking the viewer, until the pointer leaves
  controls.enableZoom = false;
  canvas.addEventListener("pointerdown", () => { controls.enableZoom = true; container.classList.add("is-active"); });
  canvas.addEventListener("pointerleave", (e) => {
    if (e.pointerType === "mouse") { controls.enableZoom = false; container.classList.remove("is-active"); }
  });
  // touch: pinch-zoom is always allowed (it never scrolls the page anyway)
  canvas.addEventListener("touchstart", () => { controls.enableZoom = true; }, { passive: true });

  // ---- Eye-Dome Lighting: render the scene to a texture with depth, then shade it on a full-screen triangle
  const target = new THREE.WebGLRenderTarget(1, 1, { depthTexture: new THREE.DepthTexture(1, 1) });
  const edlMaterial = new THREE.ShaderMaterial({
    vertexShader: EDL_VERTEX,
    fragmentShader: EDL_FRAGMENT,
    uniforms: {
      tColor: { value: target.texture },
      tDepth: { value: target.depthTexture },
      uTexel: { value: new THREE.Vector2() },
      uNear: { value: camera.near },
      uFar: { value: camera.far },
      uStrength: { value: EDL_STRENGTH },
    },
    depthTest: false,
    depthWrite: false,
  });
  const screenTriangle = new THREE.BufferGeometry();
  screenTriangle.setAttribute("position", new THREE.Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3));
  screenTriangle.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 2, 0, 0, 2], 2));
  const edlScene = new THREE.Scene();
  const edlMesh = new THREE.Mesh(screenTriangle, edlMaterial);
  edlMesh.frustumCulled = false;
  edlScene.add(edlMesh);
  const edlCamera = new THREE.Camera();

  // ---- display settings, shared by all methods (toggles in the viewer)
  const settings = { points: "session", cameras: "red" };
  const pointUniforms = {
    uSessionColours: { value: [...SESSION_COLOURS, NO_SESSION].map((c) => new THREE.Vector3(...rgb01(c))) },
    uUseImage: { value: 0 },
    uTint: { value: TINT },
    uLift: { value: LIFT },
    uWorldSize: { value: POINT_WORLD_SIZE },
    uViewportHeight: { value: 1 },
  };
  const pointMaterial = new THREE.ShaderMaterial({ vertexShader: POINT_VERTEX, fragmentShader: POINT_FRAGMENT, uniforms: pointUniforms });

  const overlay = container.querySelector(".viewer-overlay");
  const loader = new PLYLoader();
  // Read the colours as raw 0-255 custom attributes: PLYLoader's own 'color' attribute is converted from sRGB to
  // linear, which would darken them since this viewer passes colours straight through.
  loader.setCustomPropertyNameMapping({ imageRGB: ["red", "green", "blue"], sessionId: ["session"] });
  const cache = {};       // key -> Promise<{ points, frustums }>
  let current = null;
  let requested = null;

  function buildFrustums(cams) {
    // each camera: apex (0) + image corners (1-4) -> 8 edges: 4 apex-to-corner, 4 around the image rectangle
    const positions = [];
    const sessions = [];
    for (const { s, f } of cams) {
      const p = (i) => f.slice(3 * i, 3 * i + 3);
      for (const [a, b] of [[0, 1], [0, 2], [0, 3], [0, 4], [1, 2], [2, 3], [3, 4], [4, 1]]) {
        positions.push(...p(a), ...p(b));
        sessions.push(s, s);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(positions.length), 3));
    geometry.userData.sessions = sessions;
    return new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true }));
  }

  function colourFrustums(lines) {
    const colours = lines.geometry.attributes.color;
    lines.geometry.userData.sessions.forEach((s, i) => {
      const c = settings.cameras === "red" ? CAMERA_RED : (SESSION_COLOURS[s] || NO_SESSION);
      colours.setXYZ(i, ...rgb01(c));
    });
    colours.needsUpdate = true;
  }

  function load(key) {
    if (!cache[key]) {
      cache[key] = Promise.all([
        loader.loadAsync(`${BASE}_${key}.ply`),
        fetch(`${BASE}_${key}_cams.json`).then((r) => r.json()),
      ]).then(([geometry, cams]) => {
        geometry.deleteAttribute("color");   // unused (see the loader note above)
        return { points: new THREE.Points(geometry, pointMaterial), frustums: buildFrustums(cams) };
      });
      cache[key].catch(() => delete cache[key]);   // allow a retry after a network error
    }
    return cache[key];
  }

  function resetView() {
    // narrow (phone) viewers: step back so the whole cloud still fits horizontally
    camera.position.copy(START).multiplyScalar(Math.max(1, 1.35 / camera.aspect));
    controls.target.set(0, 0, 0);
    controls.update();
  }

  async function show(key) {
    requested = key;
    overlay.textContent = "Loading…";
    overlay.hidden = false;
    try {
      const item = await load(key);
      if (requested !== key) return;     // the user clicked another tab while this was loading
      if (current) { scene.remove(current.points); cameraScene.remove(current.frustums); }
      current = item;
      colourFrustums(item.frustums);
      scene.add(item.points);
      cameraScene.add(item.frustums);
      resetView();
      overlay.hidden = true;
    } catch (err) {
      if (requested === key) overlay.textContent = "Could not load the point cloud.";
      console.error(err);
    }
  }

  function applySettings() {
    pointUniforms.uUseImage.value = settings.points === "image" ? 1 : 0;
    if (current) colourFrustums(current.frustums);
    container.querySelectorAll(".viewer-toggle").forEach((group) => {
      group.querySelectorAll("button").forEach((b) => {
        const on = settings[group.dataset.setting] === b.dataset.value;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on);
      });
    });
  }
  container.querySelectorAll(".viewer-toggle button").forEach((b) => {
    b.addEventListener("click", () => {
      settings[b.closest(".viewer-toggle").dataset.setting] = b.dataset.value;
      applySettings();
    });
  });
  applySettings();

  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight || Math.round(w * 0.75);
    renderer.setSize(w, h, false);
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const size = renderer.getDrawingBufferSize(new THREE.Vector2());
    target.setSize(size.x, size.y);
    edlMaterial.uniforms.uTexel.value.set(EDL_RADIUS / size.x, EDL_RADIUS / size.y);
    pointUniforms.uViewportHeight.value = size.y;
  }
  new ResizeObserver(resize).observe(container);
  resize();

  container.querySelector(".viewer-reset").addEventListener("click", resetView);

  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.render(edlScene, edlCamera);
    renderer.autoClear = false;              // draw the frustums over the shaded image
    renderer.render(cameraScene, camera);
    renderer.autoClear = true;
  });
  return { show };
}

const container = document.getElementById("cloud-viewer");
try {
  const viewer = createViewer(container);
  container.classList.add("is-interactive");   // CSS hides the static fallback image
  window.cloudViewer = viewer;
  viewer.show(window.currentMethod || "ours");
} catch (err) {
  console.warn("Interactive viewer unavailable, keeping the static image.", err);
}
