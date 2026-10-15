import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { watchAttention } from "./app/attention";
import "./styles/app.css";

watchAttention();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

if ("serviceWorker" in navigator && !import.meta.env.DEV) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js")
      .then(() => navigator.serviceWorker.ready)
      .then((registration) => {
        /* Cache this build's files so every page opens offline. */
        registration.active?.postMessage({ type: "warm-app" });
      })
      .catch((error) => {
        console.warn("Autumn service worker registration failed:", error);
      });
  });
}
