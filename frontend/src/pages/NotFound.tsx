import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { EmptyState } from "@/components/States";

export function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      description="The page you're looking for doesn't exist."
      action={
        <Link to="/new" className="btn-primary">
          Go to New Verification
        </Link>
      }
    />
  );
}
