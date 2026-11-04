import { Navigate, useLocation } from "react-router";
export default function TimersPage() {
  const { search } = useLocation();
  return <Navigate to={`/${search}`} replace />;
}
