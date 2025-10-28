import React, { Fragment, useMemo } from "react";

import { useLiveGameSocket } from "../hooks/useLiveGameSocket";

function buildWsUrl(baseUrl, path) {
  if (baseUrl) {
    return `${baseUrl.replace(/\/$/, "")}${path}`;
  }
  if (typeof window === "undefined") {
    return path;
  }
  const { protocol, host } = window.location;
  const wsProtocol = protocol === "https:" ? "wss:" : "ws:";
  return `${wsProtocol}//${host}${path}`;
}

function ClassAnnouncementSocket({ url, onAnnouncement }) {
  useLiveGameSocket(url, {
    GAME_ANNOUNCED: event => {
      onAnnouncement(event);
    },
  });
  return null;
}

export function LiveGameAnnouncementListener({ classIds = [], wsBaseUrl, onAnnouncement }) {
  const urls = useMemo(
    () =>
      classIds.map(classId => ({
        classId,
        url: buildWsUrl(wsBaseUrl, `/ws/announce/classes/${classId}/`),
      })),
    [classIds, wsBaseUrl]
  );

  return React.createElement(
    Fragment,
    null,
    urls.map(({ classId, url }) =>
      React.createElement(ClassAnnouncementSocket, {
        key: classId,
        url,
        onAnnouncement,
      })
    )
  );
}

export default LiveGameAnnouncementListener;
