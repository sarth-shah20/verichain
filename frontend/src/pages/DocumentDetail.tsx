import { Navigate, useParams } from "react-router-dom";
export function DocumentDetail() { const { jobId, docId } = useParams(); return <Navigate replace to={`/app/${jobId}?doc=${encodeURIComponent(docId ?? "")}`} />; }
