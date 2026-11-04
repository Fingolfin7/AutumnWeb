import { Navigate, useLocation } from "react-router";
import { bootstrap } from "@/bootstrap";
import { todayKey } from "@/features/notifications/dates";
import { legacyReviewTarget } from "./periods";

export default function LegacyReviewPage() {
  const location = useLocation();
  return <Navigate replace to={legacyReviewTarget(location.pathname, location.search, todayKey(bootstrap().profile.timezone))} />;
}
