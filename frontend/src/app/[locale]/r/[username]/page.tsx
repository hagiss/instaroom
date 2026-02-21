import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { RoomViewer } from "@/components/room/room-viewer";
import { PersonaCard } from "@/components/room/persona-card";
import { ShareButtons } from "@/components/room/share-buttons";
import type { RoomResponse } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://instaroom.xyz";

async function getRoom(username: string): Promise<RoomResponse | null> {
  try {
    const res = await fetch(
      `${API_URL}/api/rooms/by-username/${username}`,
      { next: { revalidate: 0 } },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ username: string; locale: string }>;
}): Promise<Metadata> {
  const { username, locale } = await params;
  const t = await getTranslations({ locale, namespace: "room" });
  const room = await getRoom(username);

  return {
    title: t("title", { username }),
    description: room?.persona_summary || t("description", { username }),
    openGraph: {
      title: t("title", { username }),
      description: room?.persona_summary || t("description", { username }),
      url: `${SITE_URL}/r/${username}`,
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: t("title", { username }),
      description: room?.persona_summary || t("description", { username }),
    },
  };
}

export default async function RoomPage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;
  const room = await getRoom(username);

  if (!room) {
    notFound();
  }

  const shareUrl = `${SITE_URL}/r/${username}`;

  return (
    <div className="gradient-bg min-h-dvh pt-14">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {/* 3D Viewer */}
        <div
          data-viewer
          className="aspect-[4/3] w-full sm:aspect-video"
        >
          <RoomViewer viewerData={room.viewer_data} />
        </div>

        {/* Info Section */}
        <div className="mt-4 flex flex-col gap-4">
          <PersonaCard summary={room.persona_summary} />
          <ShareButtons username={username} url={shareUrl} />
        </div>
      </div>
    </div>
  );
}
