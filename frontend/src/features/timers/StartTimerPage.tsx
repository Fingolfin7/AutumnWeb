import { useNavigate } from "react-router";
import { Sheet } from "@/components/Sheet";
import { CaptureForm } from "./CaptureForm";

export default function StartTimerPage() {
  const navigate = useNavigate();
  return <><div className="today-heading"><h1 className="page-title">Today</h1></div><Sheet open onClose={() => navigate("/")} title="Capture time" className="capture-sheet"><CaptureForm /></Sheet></>;
}
