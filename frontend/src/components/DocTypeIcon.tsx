import {
  Landmark,
  FileText,
  ReceiptText,
  Banknote,
  File,
} from "lucide-react";
import type { DocType } from "@/api/types";

const MAP: Record<DocType, typeof File> = {
  bank_statement: Banknote,
  land_record: Landmark,
  itr: ReceiptText,
  salary_slip: FileText,
  unknown: File,
};

export function DocTypeIcon({
  type,
  className = "h-5 w-5",
}: {
  type: DocType;
  className?: string;
}) {
  const Icon = MAP[type];
  return <Icon className={className} aria-hidden />;
}
