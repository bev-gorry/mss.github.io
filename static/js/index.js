// Method toggle for the baseline comparison: swaps the method-specific point cloud (interactive viewer, with the
// static render as fallback), reprojection overlay and footprints, and the one-line explanation.
const METHODS = {
  colmap: {
    name: "COLMAP",
    note: "COLMAP registers only the 2017 images, so the 2016 query cannot be projected and the sessions fail to connect.",
  },
  mapanything: {
    name: "MapAnything",
    note: "MapAnything processes all images in one forward pass and absorbs the appearance changes between years, distorting the scene.",
  },
  icp: {
    name: "COLMAP + ICP",
    note: "COLMAP + ICP reconstructs sessions independently and performs registration by geometry alone. The point clouds overlap, but the image footprints are misplaced.",
  },
  bufferx: {
    name: "COLMAP + BUFFER-X",
    note: "COLMAP + BUFFER-X applies a learned point cloud registration of the independently reconstructed sessions. Coarsely aligned, with footprints still misplaced.",
  },
  ours: {
    name: "Ours",
    note: "Our method enforces cross-session correspondences during joint SfM. Projections land on the annotations and the footprints recover the expected overlap.",
  },
};

function showMethod(key) {
  window.currentMethod = key;
  if (window.cloudViewer) {
    window.cloudViewer.show(key);   // interactive viewer (pointcloud.js)
  } else {
    document.getElementById("cloud-img").src = `./static/images/s01_cloud_${key}.jpg`;   // static fallback
  }
  document.getElementById("pair-img").src = `./static/images/s01_pair_${key}.jpg`;
  document.getElementById("footprint-img").src = `./static/images/s01_footprint_${key}.jpg`;
  document.getElementById("method-note").textContent = METHODS[key].note;
  document.querySelectorAll(".method-name").forEach((el) => (el.textContent = METHODS[key].name));
  document.querySelectorAll(".method-tabs .demo-tab[data-method]").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.method === key);
  });
}

// Dataset toggle for the Joint Reconstructions viewer: swaps the full-dataset point cloud (static top view as
// fallback).

function showDataset(key) {
  window.currentDataset = key;
  if (window.fullViewer) {
    window.fullViewer.show(key);   // interactive viewer (pointcloud.js)
  } else {
    document.getElementById("full-img").src = `./static/images/recon_${key}.jpg`;   // static fallback
  }
  document.querySelectorAll(".dataset-tabs .demo-tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.dataset === key);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".dataset-tabs .demo-tab").forEach((tab) => {
    tab.addEventListener("click", () => showDataset(tab.dataset.dataset));
  });
  showDataset("sesoko");

  document.querySelectorAll(".method-tabs .demo-tab[data-method]").forEach((tab) => {
    tab.addEventListener("click", () => showMethod(tab.dataset.method));
  });
  showMethod("ours");

  // Preload the other methods' images so switching is instant
  Object.keys(METHODS).forEach((key) => {
    ["pair", "footprint"].forEach((kind) => {
      new Image().src = `./static/images/s01_${kind}_${key}.jpg`;
    });
  });
});
