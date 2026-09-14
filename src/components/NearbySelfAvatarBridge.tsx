'use client';

import { useEffect } from 'react';

const PROFILE_PHOTO_KEY = 'blee.profile-photo.v1';

function safeProfilePhoto(value: string | null) {
  if (!value || value.length > 24_000) return null;
  return /^data:image\/(?:png|jpe?g|webp);base64,/i.test(value) ? value : null;
}

export default function NearbySelfAvatarBridge() {
  useEffect(() => {
    let queued = false;
    let cachedInitial = '';
    let cachedPhoto: string | null = null;

    const captureHomeIdentity = () => {
      const homeAvatar = document.querySelector<HTMLElement>('.home-profile-button .person-avatar');
      if (!homeAvatar) return;
      const image = homeAvatar.querySelector<HTMLImageElement>('img');
      if (image?.src) {
        cachedPhoto = image.src;
        cachedInitial = '';
        return;
      }
      const initial = (homeAvatar.textContent || '').trim().slice(0, 1).toUpperCase();
      if (initial) cachedInitial = initial;
    };

    const renderSelf = (node: HTMLElement, photo: string | null, initial: string) => {
      node.replaceChildren();
      if (photo) {
        const image = document.createElement('img');
        image.src = photo;
        image.alt = '';
        image.decoding = 'async';
        node.appendChild(image);
        node.dataset.profilePhoto = 'true';
        return;
      }
      const fallback = document.createElement('span');
      fallback.className = 'radar-self-initial';
      fallback.textContent = initial || '•';
      node.appendChild(fallback);
      node.dataset.profilePhoto = 'false';
    };

    const apply = () => {
      queued = false;
      captureHomeIdentity();
      const storedPhoto = safeProfilePhoto(window.localStorage.getItem(PROFILE_PHOTO_KEY));
      const photo = storedPhoto || cachedPhoto;
      document.querySelectorAll<HTMLElement>('.radar-self-mark').forEach((node) => {
        renderSelf(node, photo, cachedInitial);
      });
    };

    const queue = () => {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(apply);
    };

    const observer = new MutationObserver(queue);
    observer.observe(document.body, { subtree: true, childList: true });
    window.addEventListener('storage', queue);
    window.addEventListener('pageshow', queue);
    queue();

    return () => {
      observer.disconnect();
      window.removeEventListener('storage', queue);
      window.removeEventListener('pageshow', queue);
    };
  }, []);

  return null;
}
