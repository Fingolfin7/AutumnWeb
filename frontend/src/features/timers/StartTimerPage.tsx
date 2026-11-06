import { useNavigate, useSearchParams } from "react-router";
import { Sheet } from "@/components/Sheet";
import HomePage from "@/features/dashboard/HomePage";
import { CaptureForm } from "./CaptureForm";

/* The URL form of capture: Today behind the sheet, never a blank page. */
export default function StartTimerPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const close = () => navigate("/");
  return <><HomePage /><Sheet open onClose={close} title="Capture time" className="capture-sheet"><CaptureForm mode={params.get("mode") === "past" ? "past" : "timer"} onSaved={close} /></Sheet></>;
}
