"use client";

import { useParams } from "next/navigation";

import { OpenLink } from "@/features/signing/OpenLink";

export default function OpenLinkRoute() {
  const { token } = useParams<{ token: string }>();
  return <OpenLink token={token} />;
}
