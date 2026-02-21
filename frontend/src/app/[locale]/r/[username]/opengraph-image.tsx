import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Instaroom";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

export default async function OgImage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;

  let screenshotUrl: string | null = null;
  try {
    const res = await fetch(
      `${API_URL}/api/rooms/by-username/${username}`,
    );
    if (res.ok) {
      const room = await res.json();
      screenshotUrl = room.screenshot_url;
    }
  } catch {
    // fallback to text-only OG
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #0a0b14 0%, #111827 50%, #0a0b14 100%)",
          fontFamily: "sans-serif",
        }}
      >
        {screenshotUrl && (
          <img
            src={screenshotUrl}
            alt=""
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              opacity: 0.4,
            }}
          />
        )}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "16px",
            zIndex: 1,
          }}
        >
          <div
            style={{
              fontSize: "28px",
              color: "#5eead4",
              letterSpacing: "0.05em",
              fontWeight: 600,
            }}
          >
            INSTAROOM
          </div>
          <div
            style={{
              fontSize: "56px",
              fontWeight: 700,
              color: "#ffffff",
            }}
          >
            {`@${username}'s Room`}
          </div>
          <div
            style={{
              fontSize: "22px",
              color: "#9ca3af",
              marginTop: "8px",
            }}
          >
            A personalized 3D room from Instagram
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
