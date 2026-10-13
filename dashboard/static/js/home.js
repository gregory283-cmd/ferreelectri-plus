(() => {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const body = document.body;
  const html = document.documentElement;

  const themeToggle = document.getElementById("themeToggle");
  const themeCurtain = document.getElementById("themeCurtain");
  const ferrebotLauncher = document.getElementById("aiAssistantFabContainer");
  const ferrebotHeroGuide = ferrebotLauncher?.querySelector("#ferrebotHeroGuide");
  const menuToggle = document.getElementById("menuToggle");
  const mobileMenu = document.getElementById("mobileMenu");
  const searchToggles = document.querySelectorAll("[data-search-toggle]");
  const searchModal = document.getElementById("searchModal");
  const searchInput = document.getElementById("searchInput");
  const searchResults = document.getElementById("searchResults");
  const closeSearch = document.getElementById("closeSearch");
  const cartToggle = document.getElementById("cart-btn");
  const cartTriggers = document.querySelectorAll("[data-cart-trigger]");
  const cartCount = document.getElementById("cartCount") || document.getElementById("cart-counter-badge");
  const cartOverlay = document.getElementById("cartOverlay");
  const cartDrawer = document.getElementById("cartDrawer");
  const cartClose = document.getElementById("cartClose");
  const cartItems = document.getElementById("cartItems");
  const cartSubtotal = document.getElementById("cartSubtotal");
  const locationLink = document.getElementById("locationLink");
  const locationModal = document.getElementById("locationModal");
  const locationClose = document.getElementById("locationClose");
  const navSearchForm = document.getElementById("navSearchForm");
  const navSearchInput = document.getElementById("navSearchInput");
  const hero = document.querySelector(".hero");
  const heroButton = document.querySelector("[data-magnet], .magnet-target");
  const navLinks = document.querySelectorAll(".nav-link, .mobile-link");
  const catalogTrack = document.getElementById("catalogTrack");
  const catalogScrollLeft = document.getElementById("catalogScrollLeft");
  const catalogScrollRight = document.getElementById("catalogScrollRight");
  const loadMoreProducts = document.getElementById("loadMoreProducts");
  const catalogSkeleton = document.getElementById("catalogSkeleton");
  const catalogSentinel = document.getElementById("catalogSentinel");

  let searchDebounceTimer;
  let searchController;
  let navSearchScrollY = null;
  const ferrebotHeroMessage = ferrebotHeroGuide?.querySelector(".ferrebot-hero-message");
  const ferrebotHeroMessageText = ferrebotHeroMessage?.textContent.trim() || "";
  let ferrebotHeroMessageTimer = null;
  let ferrebotHeroMessageStarted = false;
  let ferrebotHeroMessageComplete = false;

  function finishFerreBotHeroMessage() {
    if (ferrebotHeroMessageTimer) window.clearTimeout(ferrebotHeroMessageTimer);
    ferrebotHeroMessageTimer = null;
    if (ferrebotHeroMessage) ferrebotHeroMessage.textContent = ferrebotHeroMessageText;
    ferrebotLauncher?.classList.remove("ferrebot-thinking", "ferrebot-speaking");
    ferrebotHeroMessageComplete = true;
  }

  function startFerreBotHeroMessage() {
    if (!ferrebotHeroMessage || !ferrebotHeroMessageText || ferrebotHeroMessageStarted) return;
    ferrebotHeroMessageStarted = true;
    if (prefersReducedMotion) {
      finishFerreBotHeroMessage();
      return;
    }

    ferrebotLauncher.classList.add("ferrebot-thinking");
    ferrebotHeroMessageTimer = window.setTimeout(() => {
      ferrebotLauncher.classList.remove("ferrebot-thinking");
      ferrebotLauncher.classList.add("ferrebot-speaking");
      let characterIndex = 0;

      function writeNextCharacter() {
        characterIndex += 1;
        ferrebotHeroMessage.textContent = ferrebotHeroMessageText.slice(0, characterIndex);
        if (characterIndex < ferrebotHeroMessageText.length) {
          ferrebotHeroMessageTimer = window.setTimeout(writeNextCharacter, 28);
          return;
        }
        ferrebotHeroMessageTimer = null;
        ferrebotHeroMessageComplete = true;
        ferrebotLauncher.classList.remove("ferrebot-speaking");
      }

      writeNextCharacter();
    }, 420);
  }

  function updateFerreBotLauncher() {
    if (!ferrebotLauncher || body.classList.contains("ferrebot-open")) return;

    const heroStage = document.querySelector("#inicio .hero-mascot-stage");
    const heroBounds = heroStage?.getBoundingClientRect();
    const showInHero = heroBounds
      && window.scrollY < 180
      && heroBounds.bottom > 140
      && heroBounds.top < window.innerHeight * 0.85;

    if (showInHero) {
      ferrebotLauncher.classList.add("ferrebot-is-hero");
      if (ferrebotHeroGuide) ferrebotHeroGuide.hidden = false;
      if (ferrebotHeroGuide) ferrebotHeroGuide.setAttribute("aria-hidden", "false");
      startFerreBotHeroMessage();
      const launcherHalfWidth = ferrebotLauncher.offsetWidth / 2;
      const viewportWidth = document.documentElement.clientWidth;
      const safeCenterX = Math.min(
        viewportWidth - launcherHalfWidth - 16,
        Math.max(launcherHalfWidth + 16, heroBounds.left + heroBounds.width / 2)
      );
      ferrebotLauncher.style.left = `${safeCenterX}px`;
      ferrebotLauncher.style.top = `${heroBounds.top + heroBounds.height * 0.46}px`;
      ferrebotLauncher.style.bottom = "auto";
      ferrebotLauncher.style.transform = "translate(-50%, -50%)";
    } else {
      ferrebotLauncher.classList.remove("ferrebot-is-hero");
      if (ferrebotHeroGuide) ferrebotHeroGuide.hidden = true;
      if (ferrebotHeroGuide) ferrebotHeroGuide.setAttribute("aria-hidden", "true");
      if (ferrebotHeroMessageStarted && !ferrebotHeroMessageComplete) finishFerreBotHeroMessage();
      ferrebotLauncher.style.left = "1.25rem";
      ferrebotLauncher.style.top = `${window.innerHeight - ferrebotLauncher.offsetHeight - 20}px`;
      ferrebotLauncher.style.bottom = "auto";
      ferrebotLauncher.style.transform = "none";
    }
    ferrebotLauncher.classList.remove("ferrebot-launcher-pending");
  }

  window.updateFerreBotLauncher = updateFerreBotLauncher;
  document.addEventListener("DOMContentLoaded", updateFerreBotLauncher, { once: true });
  window.addEventListener("scroll", updateFerreBotLauncher, { passive: true });
  window.addEventListener("resize", updateFerreBotLauncher);

  function openCurtainAndRun(callback) {
    if (!themeCurtain) {
      callback();
      return;
    }

    themeCurtain.animate(
      [
        { clipPath: "circle(0% at 50% 50%)", transform: "scale(0.2)" },
        { clipPath: "circle(140% at 50% 50%)", transform: "scale(1)" },
        { clipPath: "circle(0% at 50% 50%)", transform: "scale(0.2)" }
      ],
      {
        duration: 760,
        easing: "cubic-bezier(.2,.8,.2,1)"
      }
    );

    window.setTimeout(callback, 140);
  }

  function setTheme(nextTheme, persist = true) {
    const isLight = nextTheme === "light";
    body.classList.toggle("theme-light", isLight);
    body.classList.toggle("theme-dark", !isLight);
    html.dataset.theme = isLight ? "light" : "dark";
    html.classList.toggle("dark", !isLight);
    themeToggle?.setAttribute("aria-label", isLight ? "Activar modo oscuro" : "Activar modo claro");
    themeToggle?.setAttribute("aria-pressed", String(isLight));
    const themeIcon = themeToggle?.querySelector("i");
    themeIcon?.classList.toggle("fa-sun", !isLight);
    themeIcon?.classList.toggle("fa-moon", isLight);
    if (persist) {
      try { localStorage.setItem("fe-theme", nextTheme); } catch (error) {}
    }
  }

  let savedTheme = "dark";
  try { savedTheme = localStorage.getItem("fe-theme") === "light" ? "light" : "dark"; } catch (error) {}
  setTheme(savedTheme, false);

  themeToggle?.addEventListener("click", () => {
    const nextTheme = body.classList.contains("theme-light") ? "dark" : "light";
    openCurtainAndRun(() => setTheme(nextTheme));
  });

  menuToggle?.addEventListener("click", () => {
    const isOpen = mobileMenu?.classList.toggle("is-open");
    mobileMenu?.setAttribute("aria-hidden", isOpen ? "false" : "true");
    menuToggle?.setAttribute("aria-expanded", String(Boolean(isOpen)));
  });

  mobileMenu?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      mobileMenu.classList.remove("is-open");
      mobileMenu.setAttribute("aria-hidden", "true");
      menuToggle?.setAttribute("aria-expanded", "false");
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !mobileMenu?.classList.contains("is-open")) return;
    mobileMenu.classList.remove("is-open");
    mobileMenu.setAttribute("aria-hidden", "true");
    menuToggle?.setAttribute("aria-expanded", "false");
  });

  function openSearch(focus = true) {
    if (!searchModal) return;
    searchModal.classList.add("is-open");
    searchModal.setAttribute("aria-hidden", "false");
    if (focus) window.setTimeout(() => searchInput?.focus({ preventScroll: true }), 50);
  }

  function closeSearchModal() {
    if (!searchModal) return;
    searchModal.classList.remove("is-open");
    searchModal.setAttribute("aria-hidden", "true");
  }

  searchToggles.forEach((button) => button.addEventListener("click", () => openSearch()));
  closeSearch?.addEventListener("click", closeSearchModal);

  navSearchInput?.addEventListener("pointerdown", () => {
    navSearchScrollY = window.scrollY;
  });

  navSearchInput?.addEventListener("focus", () => {
    if (navSearchScrollY === null) navSearchScrollY = window.scrollY;
    const scrollPosition = navSearchScrollY;
    window.requestAnimationFrame(() => window.scrollTo(0, scrollPosition));
  });

  navSearchInput?.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (document.activeElement !== searchInput) navSearchScrollY = null;
    }, 500);
  });

  searchModal?.addEventListener("click", (event) => {
    if (event.target === searchModal) closeSearchModal();
  });

  navSearchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = navSearchInput?.value.trim() || "";
    if (query.length < 2) {
      openSearch();
      return;
    }
    const url = new URL(navSearchForm.action, window.location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("vista", "catalogo");
    url.hash = "productos-grid";
    window.location.assign(url);
  });

  navSearchInput?.addEventListener("input", (event) => {
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(() => {
      const query = event.target.value.trim();
      if (query.length < 2) {
        searchController?.abort();
        if (searchInput) searchInput.value = query;
        if (searchResults) searchResults.textContent = query ? "Escribe al menos 2 caracteres para buscar en el catálogo." : "";
        if (!query) closeSearchModal();
        return;
      }
      const scrollPosition = navSearchScrollY ?? window.scrollY;
      if (searchInput) searchInput.value = query;
      openSearch(false);
      searchInput?.focus({ preventScroll: true });
      window.scrollTo(0, scrollPosition);
      window.requestAnimationFrame(() => window.scrollTo(0, scrollPosition));
      renderSearchResults(query);
    }, 260);
  });

  function openCartDrawer() {
    cartDrawer?.classList.add("is-open");
    cartOverlay?.classList.add("is-open");
    cartDrawer?.removeAttribute("inert");
    cartOverlay?.setAttribute("aria-hidden", "false");
    body.classList.add("drawer-open");
  }

  function closeCartDrawer() {
    cartDrawer?.classList.remove("is-open");
    cartOverlay?.classList.remove("is-open");
    if (cartDrawer?.contains(document.activeElement)) {
      cartToggle?.focus({ preventScroll: true });
    }
    cartDrawer?.setAttribute("inert", "");
    cartOverlay?.setAttribute("aria-hidden", "true");
    body.classList.remove("drawer-open");
  }

  // Mantiene el contenido fuera del árbol de interacción mientras el drawer está cerrado.
  cartDrawer?.setAttribute("inert", "");

  cartToggle?.addEventListener("click", openCartDrawer);
  cartTriggers.forEach((trigger) => trigger.addEventListener("click", openCartDrawer));
  cartClose?.addEventListener("click", closeCartDrawer);
  cartOverlay?.addEventListener("click", closeCartDrawer);

  function renderCartItem(form, itemData) {
    if (!cartItems) return;
    const card = form.closest(".product-card");
    const title = card?.querySelector(".product-title")?.textContent?.trim() || "Producto agregado";
    const code = card?.querySelector(".product-code")?.textContent?.trim() || "";
    const price = card?.querySelector(".product-price")?.textContent?.trim() || "";
    const emptyState = cartItems.querySelector(".cart-empty");
    emptyState?.remove();

    const item = document.createElement("div");
    item.className = "cart-drawer-item";
    item.innerHTML = `<div><strong>${title}</strong><small>${code} · Cantidad ${itemData.quantity}</small></div><span>${price}</span>`;
    cartItems.prepend(item);
    if (cartSubtotal && itemData.total !== undefined) {
      cartSubtotal.textContent = Number(itemData.total).toFixed(2);
    }
  }

  function getCookie(name) {
    const cookie = document.cookie.split("; ").find((entry) => entry.startsWith(`${name}=`));
    return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
  }

  function bindProductForms(scope = document) {
    scope.querySelectorAll(".product-form").forEach((form) => {
      if (form.dataset.ajaxBound === "true") return;
      form.dataset.ajaxBound = "true";
      form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type='submit']");
      if (button) button.disabled = true;

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json"
          },
          redirect: "follow"
        });
        if (!response.ok) throw new Error("No se pudo agregar el producto");
        const itemData = await response.json();
        if (!itemData.success) throw new Error(itemData.error || "No se pudo agregar el producto");
        renderCartItem(form, itemData);
        bumpCartCounter(itemData.count);
        openCartDrawer();
      } catch (error) {
        const message = error.message || "No se pudo agregar el producto al carrito.";
        if (typeof showToast === 'function') {
          showToast(message);
        } else {
          alert(message);
        }
        if (button) button.textContent = "Reintentar";
      } finally {
        if (button) button.disabled = false;
      }
      });
    });
  }

  bindProductForms();

  function openLocationModal(event) {
    event?.preventDefault();
    if (!locationModal) return;
    locationModal.hidden = false;
    document.body.classList.add("modal-open");
  }

  function closeLocationModal() {
    if (!locationModal) return;
    locationModal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  locationLink?.addEventListener("click", openLocationModal);
  locationClose?.addEventListener("click", closeLocationModal);
  locationModal?.addEventListener("click", (event) => {
    if (event.target === locationModal) closeLocationModal();
  });

  window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "k") {
      event.preventDefault();
      openSearch();
    }
    if (key === "escape") {
      closeSearchModal();
      closeCartDrawer();
      closeLocationModal();
      mobileMenu?.classList.remove("is-open");
      mobileMenu?.setAttribute("aria-hidden", "true");
    }
  });

  function renderSearchResults(query) {
    if (!searchResults) return;
    const normalized = query.trim();
    searchController?.abort();
    if (normalized.length < 2) {
      searchResults.textContent = "Escribe al menos 2 caracteres para buscar en el catálogo.";
      return;
    }

    searchController = new AbortController();
    searchResults.textContent = "Buscando productos...";
    fetch(`/api/catalog/search/?q=${encodeURIComponent(normalized)}`, {
      credentials: "same-origin",
      signal: searchController.signal,
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then((response) => {
        if (!response.ok) throw new Error("search");
        return response.json();
      })
      .then((data) => {
        searchResults.textContent = "";
        if (!data.results.length) {
          searchResults.textContent = "No hay productos que coincidan con esa búsqueda.";
          return;
        }
        data.results.forEach((product) => {
          const link = document.createElement("a");
          link.className = "search-hit search-product-hit";
          link.href = product.url;
          const image = document.createElement("img");
          image.src = product.image_url;
          image.alt = "";
          image.loading = "lazy";
          const details = document.createElement("span");
          details.className = "search-product-details";
          const name = document.createElement("strong");
          name.textContent = product.name;
          const meta = document.createElement("small");
          meta.textContent = `${product.code} · ${product.category} · ${product.stock > 0 ? `${product.stock} disponibles` : "Agotado"}`;
          const price = document.createElement("strong");
          price.className = "search-product-price";
          price.textContent = `$${product.price}`;
          details.append(name, meta);
          link.append(image, details, price);
          searchResults.appendChild(link);
        });
      })
      .catch((error) => {
        if (error.name !== "AbortError") searchResults.textContent = "No se pudo consultar el catálogo. Inténtalo de nuevo.";
      });
  }

  searchInput?.addEventListener("input", (event) => {
    if (navSearchInput) navSearchInput.value = event.target.value;
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(() => renderSearchResults(event.target.value), 180);
  });

  searchInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const query = searchInput.value.trim();
    if (query.length < 2 || !navSearchForm) return;
    event.preventDefault();
    const url = new URL(navSearchForm.action, window.location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("vista", "catalogo");
    url.hash = "productos-grid";
    window.location.assign(url);
  });

  renderSearchResults("");

  const sections = document.querySelectorAll("section[id]");
  const navItems = document.querySelectorAll(".nav-link");

  function setActiveNav() {
    if (!sections.length || !navItems.length) return;
    const scrollPosition = window.scrollY + 140;
    let activeId = "";

    sections.forEach((section) => {
      if (scrollPosition >= section.offsetTop) {
        activeId = section.id;
      }
    });

    navItems.forEach((item) => {
      const href = item.getAttribute("href") || "";
      item.classList.toggle("is-active", href === `#${activeId}`);
    });
  }

  window.addEventListener("scroll", setActiveNav, { passive: true });
  window.addEventListener("load", setActiveNav);

  if (cartCount) {
    const current = Number.parseInt(cartCount.textContent || "0", 10);
    cartCount.textContent = Number.isNaN(current) ? "0" : String(current);
  }

  function bumpCartCounter(nextValue = null) {
    if (!cartCount) return;
    const current = Number.parseInt(cartCount.textContent || "0", 10);
    const value = nextValue === null ? current + 1 : nextValue;
    cartCount.textContent = String(value);
    cartCount.animate(
      [
        { transform: "scale(1)" },
        { transform: "scale(1.28)" },
        { transform: "scale(0.96)" },
        { transform: "scale(1)" }
      ],
      { duration: 380, easing: "cubic-bezier(.2,.8,.2,1)" }
    );
  }

  function initMagnet() {
    if (!heroButton) return;

    heroButton.addEventListener("mousemove", (event) => {
      const rect = heroButton.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const deltaX = event.clientX - centerX;
      const deltaY = event.clientY - centerY;
      const distance = Math.hypot(deltaX, deltaY);
      const maxDistance = 50;

      if (distance < maxDistance) {
        const strength = (maxDistance - distance) / maxDistance;
        const moveX = deltaX * strength * 0.28;
        const moveY = deltaY * strength * 0.28;
        heroButton.style.transform = `translate(${moveX}px, ${moveY}px) scale(${1 + strength * 0.04})`;
      }
    });

    heroButton.addEventListener("mouseleave", () => {
      heroButton.style.transform = "translate(0, 0) scale(1)";
    });
  }

  initMagnet();

  function scrollCatalog(direction) {
    if (!catalogTrack) return;
    const amount = Math.max(280, catalogTrack.clientWidth * 0.72);
    catalogTrack.scrollBy({
      left: direction * amount,
      behavior: "smooth"
    });
  }

  catalogScrollLeft?.addEventListener("click", () => scrollCatalog(-1));
  catalogScrollRight?.addEventListener("click", () => scrollCatalog(1));

  let loadingProducts = false;

  function toggleSkeleton(show) {
    if (!catalogSkeleton) return;
    catalogSkeleton.classList.toggle("is-loading", show);
  }

  function cloneProductCard(card) {
    const clone = card.cloneNode(true);
    clone.dataset.cloned = "true";
    return clone;
  }

  function loadMoreCatalogItems() {
    if (!catalogTrack || loadingProducts) return;
    loadingProducts = true;
    toggleSkeleton(true);

    window.setTimeout(() => {
      const cards = Array.from(catalogTrack.querySelectorAll("[data-product-card]"));
      const sourceCards = cards.slice(0, Math.min(3, cards.length));
      sourceCards.forEach((card) => {
        catalogTrack.appendChild(cloneProductCard(card));
      });

      toggleSkeleton(false);
      loadingProducts = false;
      bumpCartCounter(Number.parseInt(cartCount?.textContent || "0", 10));
    }, 900);
  }

  loadMoreProducts?.addEventListener("click", loadMoreCatalogItems);

  if (catalogSentinel && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          loadMoreCatalogItems();
        }
      });
    }, { root: null, threshold: 0.2 });

    observer.observe(catalogSentinel);
  }

  function initHeroThree() {
    if (!hero || prefersReducedMotion || !window.THREE) return;

    const canvas = document.getElementById("hero-canvas");
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.z = 9;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true
    });

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    const group = new THREE.Group();
    scene.add(group);

    const metalMaterial = new THREE.MeshStandardMaterial({
      color: 0xb0c2d1,
      metalness: 1,
      roughness: 0.22
    });

    const darkMaterial = new THREE.MeshStandardMaterial({
      color: 0x4f5c6f,
      metalness: 0.92,
      roughness: 0.38
    });

    const torus = new THREE.Mesh(
      new THREE.TorusGeometry(1.3, 0.2, 16, 90),
      metalMaterial
    );
    torus.rotation.x = Math.PI / 2;
    group.add(torus);

    const gear = new THREE.Mesh(
      new THREE.CylinderGeometry(0.9, 0.9, 0.28, 14),
      darkMaterial
    );
    gear.rotation.z = Math.PI / 2;
    gear.position.set(-2.6, -0.55, -0.85);
    group.add(gear);

    const screwHead = new THREE.Mesh(
      new THREE.CylinderGeometry(0.3, 0.3, 0.16, 6),
      metalMaterial
    );
    screwHead.position.set(2.2, 0.6, 0.1);
    group.add(screwHead);

    const screwStem = new THREE.Mesh(
      new THREE.CylinderGeometry(0.07, 0.07, 1.35, 16),
      darkMaterial
    );
    screwStem.rotation.z = Math.PI / 4;
    screwStem.position.set(2.25, 0.05, -0.1);
    group.add(screwStem);

    const ring = new THREE.Mesh(
      new THREE.TorusKnotGeometry(0.85, 0.16, 120, 14),
      metalMaterial
    );
    ring.position.set(0.2, 1.8, -0.8);
    group.add(ring);

    const particleGeometry = new THREE.BufferGeometry();
    const particleCount = 720;
    const particlePositions = new Float32Array(particleCount * 3);

    for (let index = 0; index < particleCount * 3; index += 3) {
      particlePositions[index] = (Math.random() - 0.5) * 24;
      particlePositions[index + 1] = (Math.random() - 0.5) * 14;
      particlePositions[index + 2] = (Math.random() - 0.5) * 14;
    }

    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));

    const particles = new THREE.Points(
      particleGeometry,
      new THREE.PointsMaterial({
        color: 0x00d2ff,
        size: 0.03,
        transparent: true,
        opacity: 0.9
      })
    );

    scene.add(particles);

    const ambient = new THREE.AmbientLight(0xffffff, 1.9);
    scene.add(ambient);

    const keyLight = new THREE.DirectionalLight(0x00d2ff, 2.4);
    keyLight.position.set(3, 5, 8);
    scene.add(keyLight);

    const warmLight = new THREE.DirectionalLight(0xffc107, 1.3);
    warmLight.position.set(-4, -1, 4);
    scene.add(warmLight);

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2(2, 2);
    const targetRotation = { x: 0, y: 0 };

    window.addEventListener("mousemove", (event) => {
      mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
      mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
      targetRotation.x = mouse.y * 0.28;
      targetRotation.y = mouse.x * 0.42;
    });

    function animate() {
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects([torus, gear, screwHead, screwStem, ring], false);
      const hit = intersects.length > 0;

      torus.rotation.z += 0.006;
      gear.rotation.y += 0.01;
      screwHead.rotation.y += 0.009;
      screwStem.rotation.z += 0.006;
      ring.rotation.x += 0.005;
      ring.rotation.y += 0.008;

      group.rotation.y += (targetRotation.y - group.rotation.y) * 0.04;
      group.rotation.x += (targetRotation.x - group.rotation.x) * 0.04;

      particles.rotation.y += 0.0008;
      particles.material.opacity = hit ? 0.98 : 0.82;
      particles.scale.lerp(new THREE.Vector3(hit ? 1.03 : 1, hit ? 1.03 : 1, hit ? 1.03 : 1), 0.06);

      renderer.render(scene, camera);
      window.requestAnimationFrame(animate);
    }

    animate();

    window.addEventListener("resize", () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      if (mobileMenu?.classList.contains("is-open")) {
        mobileMenu.classList.remove("is-open");
        mobileMenu.setAttribute("aria-hidden", "true");
      }
    });
  });

})();
