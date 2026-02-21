import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="gradient-bg flex min-h-dvh flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">Page not found</p>
      <Button asChild variant="outline">
        <Link href="/">Go Home</Link>
      </Button>
    </div>
  );
}
