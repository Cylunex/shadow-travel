import { MapPinOff } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "../components/Shared";

export function NotFoundPage() {
  const navigate = useNavigate();
  return <div className="content-page"><EmptyState icon={<MapPinOff />} title="这条路没有画在地图上">页面可能已经移动，回到全局地图继续看看。<button className="primary-button" type="button" onClick={() => navigate("/")}>返回全局地图</button></EmptyState></div>;
}
