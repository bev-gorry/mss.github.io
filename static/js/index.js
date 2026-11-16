// Method toggle for the baseline comparison: swaps the three method-specific images
// (point cloud, reprojection overlay, footprints) and the one-line explanation.
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
    note: "COLMAP + ICP reconstructs sessions independently and performs registration by geometry alone. The pointclouds overlap, but the image footprints are misplaced.",
  },
  bufferx: {
    name: "COLMAP + BUFFER-X",
    note: "COLMAP + BUFFER-X presents a learned point cloud registration of the independently reconstructed sessions. Coarsely aligned, with footprints still misplaced.",
  },
  ours: {
    name: "Ours",
    note: "Our method enforces cross-session correspondences during joint SfM. Projections land on the annotations and the footprints recover the expected overlap.",
  },
};

function showMethod(key) {
  document.getElementById("cloud-img").src = `./static/images/s01_cloud_${key}.jpg`;
  document.getElementById("pair-img").src = `./static/images/s01_pair_${key}.jpg`;
  document.getElementById("footprint-img").src = `./static/images/s01_footprint_${key}.jpg`;
  document.getElementById("method-note").textContent = METHODS[key].note;
  document.querySelectorAll(".method-name").forEach((el) => (el.textContent = METHODS[key].name));
  document.querySelectorAll(".method-tabs .demo-tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.method === key);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".method-tabs .demo-tab").forEach((tab) => {
    tab.addEventListener("click", () => showMethod(tab.dataset.method));
  });
  showMethod("ours");

  // Preload the other methods' images so switching is instant
  Object.keys(METHODS).forEach((key) => {
    ["cloud", "pair", "footprint"].forEach((kind) => {
      new Image().src = `./static/images/s01_${kind}_${key}.jpg`;
    });
  });
});
