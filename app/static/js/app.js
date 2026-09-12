// Theme toggle
function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

document.addEventListener("DOMContentLoaded", () => {
  const toggleBtn = document.getElementById("theme-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", async () => {
      const isLight = document.documentElement.getAttribute("data-theme") === "light";
      applyTheme(isLight); // flip
      try {
        const res = await fetch("/settings/toggle-theme", { method: "POST" });
        const data = await res.json();
        applyTheme(data.dark_mode);
      } catch (e) { /* offline demo mode: local toggle still worked */ }
    });
  }

  // Split type toggle buttons
  document.querySelectorAll("[data-split-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-split-btn]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("split_type").value = btn.dataset.splitBtn;
      document.querySelectorAll("[data-split-panel]").forEach(p => {
        p.style.display = (p.dataset.splitPanel === btn.dataset.splitBtn) ? "block" : "none";
      });
    });
  });

  // Receipt OCR scan
  const ocrInput = document.getElementById("receipt");
  const ocrStatus = document.getElementById("ocr-status");
  if (ocrInput) {
    ocrInput.addEventListener("change", async () => {
      if (!ocrInput.files.length) return;
      ocrStatus.textContent = "Scanning receipt...";
      const fd = new FormData();
      fd.append("receipt", ocrInput.files[0]);
      try {
        const res = await fetch("/ocr/scan", { method: "POST", body: fd });
        const data = await res.json();
        if (data.ok && data.guessed_amount) {
          ocrStatus.textContent = `Detected amount: ₹${data.guessed_amount} (edit if incorrect)`;
          const amountField = document.getElementById("total_amount");
          if (amountField && !amountField.value) amountField.value = data.guessed_amount;
        } else {
          ocrStatus.textContent = data.error || "Couldn't read an amount — please enter it manually.";
        }
      } catch (e) {
        ocrStatus.textContent = "OCR scan failed — enter the amount manually.";
      }
    });
  }
});
