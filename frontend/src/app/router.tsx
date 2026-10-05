import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "./Layout";
import { NewVerification } from "@/pages/NewVerification";
import { Queue } from "@/pages/Queue";
import { Processing } from "@/pages/Processing";
import { Results } from "@/pages/Results";
import { DocumentDetail } from "@/pages/DocumentDetail";
import { ApplicantFile } from "@/pages/ApplicantFile";
import { History } from "@/pages/History";
import { Settings } from "@/pages/Settings";
import { NotFound } from "@/pages/NotFound";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/queue" replace /> },
      { path: "queue", element: <Queue /> },
      { path: "new", element: <NewVerification /> },
      { path: "processing/:jobId", element: <Processing /> },
      { path: "results/:jobId", element: <Results /> },
      { path: "app/:jobId", element: <ApplicantFile /> },
      { path: "results/:jobId/doc/:docId", element: <DocumentDetail /> },
      { path: "history", element: <History /> },
      { path: "settings", element: <Settings /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
