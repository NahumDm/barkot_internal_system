"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  addBonoPairings,
  createBonoType,
  getBonoDaySummary,
  listBonoConfigHistory,
  listBonoTypes,
  removeBonoPairing,
  resolveBonoPairingReview,
  updateBonoType,
  type BonoConfigHistoryEntry,
  type BonoDaySummary,
  type BonoPairing,
  type BonoReviewResolution,
  type BonoType,
} from "@/lib/api/bono";
import { listProducts, type ProductListItem } from "@/lib/api/products";
import { useT } from "@/lib/i18n/context";
import { useBonoPermissions } from "./permissions";
import { BonoColorDot, BonoPageHeader, LoadingNote, formatDay, formatTimestamp } from "./parts";

const BOTTLE_UNITS = new Set(["bottle", "bottles", "btl"]);

function messageOf(value: unknown, fallback: string): string {
  const message = (value as { message?: unknown }).message;
  return typeof message === "string" && message ? message : fallback;
}

function isBottleProduct(product: ProductListItem): boolean {
  return (
    product.is_active &&
    product.is_stock_tracked &&
    product.quantity_mode === "WHOLE" &&
    BOTTLE_UNITS.has(product.unit.trim().toLowerCase())
  );
}

function PairingReviewForm({
  pairing,
  types,
  currency,
  busy,
  onCancel,
  onSubmit,
}: Readonly<{
  pairing: BonoPairing;
  types: BonoType[];
  currency: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: {
    resolution: BonoReviewResolution;
    reason: string;
    target_bono_type?: number | null;
  }) => void;
}>) {
  const t = useT();
  const [resolution, setResolution] = useState<BonoReviewResolution>("RETAIN");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim()) {
      setError(t("bono.cfg.reviewReasonRequired"));
      return;
    }
    if (resolution === "REASSIGN" && !target) {
      setError(t("bono.cfg.chooseDifferentType"));
      return;
    }
    setError("");
    onSubmit({
      resolution,
      reason: reason.trim(),
      target_bono_type: resolution === "REASSIGN" ? Number(target) : null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 rounded border border-amber-200 bg-amber-50 p-3">
      <p className="text-sm font-semibold text-amber-950">{t("bono.cfg.resolvePriceReview")}</p>
      <p className="mt-1 text-xs text-amber-950">{pairing.review_reason}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium text-ink">
          {t("bono.cfg.resolution")}
          <select
            className="control mt-1.5"
            value={resolution}
            onChange={(event) => setResolution(event.target.value as BonoReviewResolution)}
          >
            <option value="RETAIN">{t("bono.cfg.retain")}</option>
            <option value="REASSIGN">{t("bono.cfg.reassign")}</option>
            <option value="UNPAIR">{t("bono.cfg.unpair")}</option>
          </select>
        </label>
        {resolution === "REASSIGN" ? (
          <label className="text-sm font-medium text-ink">
            {t("bono.cfg.targetType")}
            <select
              className="control mt-1.5"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              <option value="">{t("bono.cfg.chooseTypePlaceholder")}</option>
              {types
                .filter((type) => type.id !== pairing.bono_type.id && type.is_active)
                .map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name} ({type.selling_price} {type.currency})
                  </option>
                ))}
            </select>
          </label>
        ) : null}
        <label className="text-sm font-medium text-ink sm:col-span-2">
          {t("bono.cfg.reason")}
          <input
            type="text"
            className="control mt-1.5"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("bono.cfg.resolveReason")}
          />
        </label>
      </div>
      {resolution === "RETAIN" ? (
        <p className="mt-2 text-xs text-amber-950">
          {t("bono.cfg.retainHint").replace("{currency}", currency)}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="form-error mt-2">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? t("bono.cfg.resolving") : t("bono.cfg.resolveReview")}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

export default function BonoConfigurationPage() {
  const permissions = useBonoPermissions();
  const t = useT();
  const [types, setTypes] = useState<BonoType[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [summary, setSummary] = useState<BonoDaySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [confirmInProgress, setConfirmInProgress] = useState(false);

  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState("#8e192f");
  const [newPrice, setNewPrice] = useState("0.00");
  const [newNotes, setNewNotes] = useState("");

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("#8e192f");
  const [editNotes, setEditNotes] = useState("");
  const [editActive, setEditActive] = useState(true);

  const [selectedProduct, setSelectedProduct] = useState<Record<number, string>>({});
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [removeReason, setRemoveReason] = useState("");
  const [reviewId, setReviewId] = useState<number | null>(null);

  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const [history, setHistory] = useState<BonoConfigHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [typePage, productPage, day] = await Promise.all([
        listBonoTypes(),
        listProducts({ query: { active: true, page_size: 200 } }),
        getBonoDaySummary(),
      ]);
      setTypes(typePage.results);
      setProducts(productPage.results.filter(isBottleProduct));
      setSummary(day);
      setError("");
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!permissions.configure) return;
    let active = true;
    Promise.all([
      listBonoTypes(),
      listProducts({ query: { active: true, page_size: 200 } }),
      getBonoDaySummary(),
    ])
      .then(([typePage, productPage, day]) => {
        if (!active) return;
        setTypes(typePage.results);
        setProducts(productPage.results.filter(isBottleProduct));
        setSummary(day);
        setError("");
      })
      .catch((value: unknown) => {
        if (active) setError(messageOf(value, t("bono.cfg.saveFailed")));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [permissions.configure]);

  const openDates = summary?.in_progress_dates ?? [];
  const needsConfirmation = openDates.length > 0;
  const activeProductIds = new Set(
    types.flatMap((type) => type.active_pairings.map((pairing) => pairing.product)),
  );

  function guardOpenDays(): boolean {
    if (!needsConfirmation) return true;
    if (!confirmInProgress) {
      setError(t("bono.cfg.confirmFirst"));
      return false;
    }
    if (!changeReason.trim()) {
      setError(t("bono.cfg.writtenReasonRequired"));
      return false;
    }
    return true;
  }

  function confirmationFields() {
    return {
      confirm_in_progress: needsConfirmation ? confirmInProgress : false,
      change_reason: changeReason.trim(),
    };
  }

  async function handleCreateType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("create");
    setError("");
    setSuccess("");
    try {
      await createBonoType({
        name: newName.trim(),
        color: newColor,
        selling_price: newPrice,
        notes: newNotes.trim(),
      });
      setNewName("");
      setNewColor("#8e192f");
      setNewPrice("0.00");
      setNewNotes("");
      setSuccess(t("bono.cfg.typeCreated"));
      await load();
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setBusy("");
    }
  }

  function startEdit(type: BonoType) {
    setEditingId(type.id);
    setEditName(type.name);
    setEditColor(type.color);
    setEditNotes(type.notes);
    setEditActive(type.is_active);
    setError("");
    setSuccess("");
  }

  async function handleSaveType(event: FormEvent<HTMLFormElement>, type: BonoType) {
    event.preventDefault();
    if (!guardOpenDays()) return;
    setBusy(`type-${type.id}`);
    setError("");
    setSuccess("");
    try {
      await updateBonoType(type.id, {
        name: editName.trim(),
        color: editColor,
        notes: editNotes.trim(),
        is_active: editActive,
        ...confirmationFields(),
      });
      setEditingId(null);
      setSuccess(editActive ? t("bono.cfg.typeUpdated") : t("bono.cfg.typeRetired"));
      await load();
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setBusy("");
    }
  }

  async function handleAddPairing(type: BonoType) {
    const raw = selectedProduct[type.id];
    if (!raw) {
      setError(t("bono.cfg.chooseProductToPair"));
      return;
    }
    if (!guardOpenDays()) return;
    setBusy(`pair-${type.id}`);
    setError("");
    setSuccess("");
    try {
      await addBonoPairings(type.id, {
        products: [Number(raw)],
        ...confirmationFields(),
      });
      setSelectedProduct((current) => ({ ...current, [type.id]: "" }));
      setSuccess(t("bono.cfg.productPaired").replace("{name}", type.name));
      await load();
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setBusy("");
    }
  }

  async function handleRemovePairing(pairing: BonoPairing) {
    if (!removeReason.trim()) {
      setError(t("bono.cfg.retirePairingReason"));
      return;
    }
    if (!guardOpenDays()) return;
    setBusy(`remove-${pairing.id}`);
    setError("");
    setSuccess("");
    try {
      await removeBonoPairing(pairing.id, {
        reason: removeReason.trim(),
        ...confirmationFields(),
      });
      setRemovingId(null);
      setRemoveReason("");
      setSuccess(t("bono.cfg.pairingRetired"));
      await load();
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setBusy("");
    }
  }

  async function handleResolveReview(
    pairing: BonoPairing,
    input: {
      resolution: BonoReviewResolution;
      reason: string;
      target_bono_type?: number | null;
    },
  ) {
    if (!guardOpenDays()) return;
    setBusy(`review-${pairing.id}`);
    setError("");
    setSuccess("");
    try {
      await resolveBonoPairingReview(pairing.id, {
        ...input,
        ...confirmationFields(),
      });
      setReviewId(null);
      setSuccess(t("bono.cfg.reviewResolved"));
      await load();
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setBusy("");
    }
  }

  async function toggleHistory(type: BonoType) {
    if (historyFor === type.id) {
      setHistoryFor(null);
      return;
    }
    setHistoryFor(type.id);
    setHistoryLoading(true);
    try {
      const page = await listBonoConfigHistory(type.id);
      setHistory(page.results);
      setError("");
    } catch (value) {
      setError(messageOf(value, t("bono.cfg.saveFailed")));
    } finally {
      setHistoryLoading(false);
    }
  }

  if (!permissions.configure) {
    return (
      <section className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          {t("common.bono")}
        </p>
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          {t("bono.cfg.noConfigPermission")}
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <BonoPageHeader
        eyebrow={t("common.bono")}
        title={t("bono.cfg.configuration")}
        description={t("bono.cfg.configDescription")}
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setLoading(true);
              void load();
            }}
          >
            {t("common.refresh")}
          </button>
        }
      />

      {needsConfirmation ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <p className="font-semibold">
            {t("bono.cfg.openActivityExists").replace(
              "{dates}",
              openDates.map(formatDay).join(", "),
            )}
          </p>
          <p className="mt-1">{t("bono.cfg.openDaysBlurb")}</p>
          <label className="mt-3 flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-1"
              checked={confirmInProgress}
              onChange={(event) => setConfirmInProgress(event.target.checked)}
            />
            <span>{t("bono.cfg.understandOpenDays")}</span>
          </label>
          <label className="mt-3 block font-medium">
            {t("bono.cfg.reasonNow")}
            <input
              type="text"
              className="control mt-1.5"
              value={changeReason}
              onChange={(event) => setChangeReason(event.target.value)}
              placeholder={t("bono.cfg.requiredWhileOpen")}
            />
          </label>
        </div>
      ) : (
        <label className="block rounded border border-border bg-surface p-4 text-sm font-medium text-ink">
          {t("bono.cfg.configNote")}{" "}
          <span className="font-normal text-ink-secondary">{t("bono.op.optional")}</span>
          <input
            type="text"
            className="control mt-1.5"
            value={changeReason}
            onChange={(event) => setChangeReason(event.target.value)}
            placeholder={t("bono.cfg.auditPlaceholder")}
          />
        </label>
      )}

      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}
      {success ? (
        <p
          role="status"
          className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950"
        >
          {success}
        </p>
      ) : null}

      <form onSubmit={handleCreateType} className="rounded border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold text-ink">{t("bono.newTypeTitle")}</h2>
        <p className="mt-1 text-sm text-ink-secondary">{t("bono.cfg.newTypeBlurb")}</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm font-medium text-ink">
            {t("bono.cfg.name")}
            <input
              type="text"
              className="control mt-1.5"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              maxLength={100}
              required
            />
          </label>
          <label className="text-sm font-medium text-ink">
            {t("bono.cfg.colour")}
            <span className="mt-1.5 flex items-center gap-2">
              <input
                type="color"
                className="h-9 w-12 cursor-pointer rounded border border-border"
                value={newColor}
                onChange={(event) => setNewColor(event.target.value)}
                aria-label={t("bono.cfg.newBonoColour")}
              />
              <input
                type="text"
                className="control"
                value={newColor}
                onChange={(event) => setNewColor(event.target.value)}
                maxLength={7}
                pattern="^#[0-9A-Fa-f]{6}$"
                aria-label={t("bono.cfg.newBonoColourHex")}
              />
            </span>
          </label>
          <label className="text-sm font-medium text-ink">
            {t("bono.cfg.sellingPrice")}
            <input
              type="number"
              min="0"
              step="0.01"
              className="control mt-1.5"
              value={newPrice}
              onChange={(event) => setNewPrice(event.target.value)}
              required
            />
          </label>
          <label className="text-sm font-medium text-ink">
            {t("bono.rd.notes")}
            <input
              type="text"
              className="control mt-1.5"
              value={newNotes}
              onChange={(event) => setNewNotes(event.target.value)}
              maxLength={500}
            />
          </label>
        </div>
        <button type="submit" className="btn btn-primary mt-4" disabled={busy !== ""}>
          {busy === "create" ? t("bono.cfg.creating") : t("bono.cfg.createBonoType")}
        </button>
      </form>

      {loading && types.length === 0 ? <LoadingNote label={t("bono.loadingConfig")} /> : null}

      <div className="space-y-5">
        {types.map((type) => {
          const pairedIds = new Set(type.active_pairings.map((pairing) => pairing.product));
          const eligible = products.filter(
            (product) =>
              !activeProductIds.has(product.id) &&
              product.current_price?.unit_price === type.selling_price &&
              product.current_price.currency === type.currency,
          );
          return (
            <article key={type.id} className="rounded border border-border bg-surface">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <BonoColorDot color={type.color} label={type.name} />
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-semibold ${
                        type.is_active
                          ? "bg-emerald-100 text-emerald-900"
                          : "bg-canvas text-ink-secondary"
                      }`}
                    >
                      {type.is_active ? t("bono.cfg.active") : t("bono.cfg.retired")}
                    </span>
                    {type.pending_review_count > 0 ? (
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">
                        {t("bono.cfg.priceReviewCount").replace(
                          "{n}",
                          String(type.pending_review_count),
                        )}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 font-mono text-xs text-ink-secondary">{type.code}</p>
                  <p className="mt-1 text-sm text-ink-secondary">
                    {type.selling_price} {type.currency} ·{" "}
                    {t("bono.cfg.activePairings").replace(
                      "{n}",
                      String(type.active_pairings.length),
                    )}
                  </p>
                  {type.notes ? (
                    <p className="mt-1 text-sm text-ink-secondary">{type.notes}</p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void toggleHistory(type)}
                  >
                    {historyFor === type.id ? t("bono.cfg.hideHistory") : t("bono.cfg.history")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => startEdit(type)}
                  >
                    {t("bono.cfg.edit")}
                  </button>
                </div>
              </div>

              {editingId === type.id ? (
                <form
                  onSubmit={(event) => void handleSaveType(event, type)}
                  className="border-b border-border bg-canvas/40 p-5"
                >
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                    <label className="text-sm font-medium text-ink">
                      {t("bono.cfg.name")}
                      <input
                        type="text"
                        className="control mt-1.5"
                        value={editName}
                        onChange={(event) => setEditName(event.target.value)}
                        maxLength={100}
                        required
                      />
                    </label>
                    <label className="text-sm font-medium text-ink">
                      {t("bono.cfg.colour")}
                      <span className="mt-1.5 flex items-center gap-2">
                        <input
                          type="color"
                          className="h-9 w-12 cursor-pointer rounded border border-border"
                          value={editColor}
                          onChange={(event) => setEditColor(event.target.value)}
                          aria-label={t("bono.cfg.colourAria").replace("{name}", type.name)}
                        />
                        <input
                          type="text"
                          className="control"
                          value={editColor}
                          onChange={(event) => setEditColor(event.target.value)}
                          maxLength={7}
                          pattern="^#[0-9A-Fa-f]{6}$"
                          aria-label={t("bono.cfg.colourHexAria").replace("{name}", type.name)}
                        />
                      </span>
                    </label>
                    <label className="text-sm font-medium text-ink sm:col-span-2">
                      {t("bono.rd.notes")}
                      <input
                        type="text"
                        className="control mt-1.5"
                        value={editNotes}
                        onChange={(event) => setEditNotes(event.target.value)}
                        maxLength={500}
                      />
                    </label>
                  </div>
                  <label className="mt-4 flex items-start gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={editActive}
                      onChange={(event) => setEditActive(event.target.checked)}
                    />
                    <span>
                      {t("bono.cfg.active")}
                      <span className="block text-xs text-ink-secondary">{t("bono.cfg.activeHint")}</span>
                    </span>
                  </label>
                  <div className="mt-4 flex gap-2">
                    <button type="submit" className="btn btn-primary" disabled={busy !== ""}>
                      {busy === `type-${type.id}`
                        ? t("bono.rd.saving")
                        : t("bono.cfg.saveChanges")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => setEditingId(null)}
                      disabled={busy !== ""}
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                </form>
              ) : null}

              <div className="p-5">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-secondary">
                  {t("bono.productPairings")}
                </h3>
                <div className="mt-3 space-y-3">
                  {type.active_pairings.map((pairing) => (
                    <div key={pairing.id} className="rounded border border-border p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="font-medium text-ink">{pairing.product_name}</p>
                          <p className="font-mono text-xs text-ink-secondary">
                            {pairing.product_sku}
                          </p>
                          <p className="mt-1 text-xs text-ink-secondary">
                            {t("bono.cfg.pairedAt")
                              .replace("{price}", pairing.price_at_pairing)
                              .replace("{currency}", pairing.currency)}
                            {pairing.current_price !== null
                              ? t("bono.cfg.currentPrice").replace(
                                  "{price}",
                                  pairing.current_price,
                                )
                              : t("bono.cfg.noCurrentPrice")}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {pairing.review_required ? (
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() =>
                                setReviewId(reviewId === pairing.id ? null : pairing.id)
                              }
                            >
                              {reviewId === pairing.id
                                ? t("bono.cfg.closeReview")
                                : t("bono.cfg.reviewPrice")}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="btn btn-ghost text-red-700"
                            onClick={() => {
                              setRemovingId(removingId === pairing.id ? null : pairing.id);
                              setRemoveReason("");
                            }}
                          >
                            {removingId === pairing.id
                              ? t("bono.cfg.keepPairing")
                              : t("bono.cfg.retirePairing")}
                          </button>
                        </div>
                      </div>
                      {pairing.review_required ? (
                        <p className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-950">
                          {pairing.review_reason}
                        </p>
                      ) : null}
                      {reviewId === pairing.id ? (
                        <PairingReviewForm
                          pairing={pairing}
                          types={types}
                          currency={type.currency}
                          busy={busy === `review-${pairing.id}`}
                          onCancel={() => setReviewId(null)}
                          onSubmit={(input) => void handleResolveReview(pairing, input)}
                        />
                      ) : null}
                      {removingId === pairing.id ? (
                        <div className="mt-3 flex flex-wrap items-end gap-2 rounded border border-red-200 bg-red-50 p-3">
                          <label className="min-w-64 flex-1 text-sm font-medium text-ink">
                            {t("bono.cfg.retirementReason")}
                            <input
                              type="text"
                              className="control mt-1.5"
                              value={removeReason}
                              onChange={(event) => setRemoveReason(event.target.value)}
                              placeholder={t("bono.cfg.whyNoLongerBelongs")}
                            />
                          </label>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => void handleRemovePairing(pairing)}
                            disabled={busy !== ""}
                          >
                            {busy === `remove-${pairing.id}`
                              ? t("bono.cfg.retiring")
                              : t("bono.cfg.confirmRetirement")}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {type.active_pairings.length === 0 ? (
                    <p className="text-sm text-ink-secondary">
                      {t("bono.cfg.noActiveProducts")}
                    </p>
                  ) : null}
                </div>

                {type.is_active ? (
                  <div className="mt-4 flex flex-wrap items-end gap-2">
                    <label className="min-w-64 flex-1 text-sm font-medium text-ink">
                      {t("bono.cfg.pairProduct")}
                      <select
                        className="control mt-1.5"
                        value={selectedProduct[type.id] ?? ""}
                        onChange={(event) =>
                          setSelectedProduct((current) => ({
                            ...current,
                            [type.id]: event.target.value,
                          }))
                        }
                        disabled={eligible.length === 0}
                      >
                        <option value="">
                          {eligible.length === 0
                            ? t("bono.cfg.noEligibleProduct")
                            : t("bono.op.chooseProduct")}
                        </option>
                        {eligible.map((product) => (
                          <option key={product.id} value={product.id}>
                            {product.name} ({product.sku}) · {product.current_price?.unit_price}{" "}
                            {product.current_price?.currency}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => void handleAddPairing(type)}
                      disabled={busy !== "" || eligible.length === 0 || !selectedProduct[type.id]}
                    >
                      {busy === `pair-${type.id}`
                        ? t("bono.cfg.pairing")
                        : t("bono.cfg.addPairing")}
                    </button>
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-ink-secondary">
                    {t("bono.cfg.retiredHint")}
                  </p>
                )}
                {pairedIds.size > 0 && eligible.length === 0 ? (
                  <p className="mt-2 text-xs text-ink-secondary">
                    {t("bono.cfg.eligibilityHint")
                      .replace("{price}", type.selling_price)
                      .replace("{currency}", type.currency)}
                  </p>
                ) : null}

                {historyFor === type.id ? (
                  <div className="mt-4 rounded border border-border">
                    <div className="border-b border-border bg-canvas p-3">
                      <h3 className="text-sm font-semibold text-ink">{t("bono.configHistory")}</h3>
                    </div>
                    {historyLoading ? (
                      <LoadingNote label={t("bono.loadingHistory")} />
                    ) : history.length === 0 ? (
                      <p className="p-4 text-sm text-ink-secondary">
                        {t("bono.cfg.noConfigHistory")}
                      </p>
                    ) : (
                      <ul className="divide-y divide-border">
                        {history.map((entry) => (
                          <li key={entry.id} className="p-3 text-sm">
                            <p className="font-medium text-ink">{entry.summary}</p>
                            <p className="mt-1 text-xs text-ink-secondary">
                              {entry.actor_name || t("bono.cfg.unknownActor")} ·{" "}
                              {formatTimestamp(entry.created_at)}
                            </p>
                            <details className="mt-1 text-xs text-ink-secondary">
                              <summary className="cursor-pointer">{t("bono.cfg.beforeAfter")}</summary>
                              <pre className="mt-2 overflow-x-auto rounded bg-canvas p-2">
                                {JSON.stringify(
                                  { before: entry.before, after: entry.after },
                                  null,
                                  2,
                                )}
                              </pre>
                            </details>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      {!loading && types.length === 0 ? (
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          {t("bono.cfg.noTypesYet")}
        </div>
      ) : null}
    </section>
  );
}
