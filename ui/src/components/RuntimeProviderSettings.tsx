import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { runtimeProvidersApi } from "../api/runtimeProviders";
import type { AgentRuntimeType, RuntimeModel, RuntimeProvider, RuntimeProviderScope } from "../api/types";
import { isEnglishLocale } from "../utils/locale";
import { MODEL_PROVIDER_RUNTIMES } from "../utils/runtimeModels";
import { Badge } from "./Badge";
import { ErrorNotice } from "./ErrorNotice";

const DEFAULT_PROTOCOL = "openai_chat_completions";

export function RuntimeProviderSettings({ orgId }: { orgId: string }) {
  const english = isEnglishLocale();
  const queryClient = useQueryClient();
  const [runtimeType, setRuntimeType] = useState<AgentRuntimeType>("opencode_local");
  const [providerId, setProviderId] = useState("");
  const [providerName, setProviderName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [protocol, setProtocol] = useState(DEFAULT_PROTOCOL);
  const [providerScope, setProviderScope] = useState<RuntimeProviderScope>("global");
  const [modelId, setModelId] = useState("");
  const [modelName, setModelName] = useState("");
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [modelDialogProviderId, setModelDialogProviderId] = useState("");
  const [editingProvider, setEditingProvider] = useState<RuntimeProvider | null>(null);
  const [editingModel, setEditingModel] = useState<{ providerId: string; model: RuntimeModel } | null>(null);

  const providers = useQuery({
    queryKey: ["runtime-providers", orgId, runtimeType],
    queryFn: () => runtimeProvidersApi.listProviders(orgId, runtimeType),
    enabled: Boolean(orgId),
  });
  const providerRows = providers.data ?? [];

  const createProvider = useMutation({
    mutationFn: () =>
      runtimeProvidersApi.createProvider(orgId, {
        scope: providerScope,
        runtimeType,
        providerId: providerId.trim(),
        name: providerName.trim() || providerId.trim(),
        protocol: protocol.trim() || DEFAULT_PROTOCOL,
        baseUrl: baseUrl.trim() || null,
        apiKey: apiKey.trim() || null,
        enabled: true,
      }),
    onSuccess: () => {
      setProviderId("");
      setProviderName("");
      setBaseUrl("");
      setApiKey("");
      setProtocol(DEFAULT_PROTOCOL);
      setProviderScope("global");
      setProviderDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["runtime-providers", orgId, runtimeType] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const updateProvider = useMutation({
    mutationFn: () =>
      runtimeProvidersApi.updateProvider(orgId, runtimeType, editingProvider!.providerId, {
        name: providerName.trim() || editingProvider!.providerId,
        protocol: protocol.trim() || DEFAULT_PROTOCOL,
        baseUrl: baseUrl.trim() || null,
        apiKey: apiKey.trim() || undefined,
        enabled: editingProvider!.enabled !== false,
      }),
    onSuccess: () => {
      clearProviderForm();
      void queryClient.invalidateQueries({ queryKey: ["runtime-providers", orgId, runtimeType] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const toggleProvider = useMutation({
    mutationFn: (provider: RuntimeProvider) =>
      runtimeProvidersApi.updateProvider(orgId, runtimeType, provider.providerId, {
        enabled: provider.enabled === false,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runtime-providers", orgId, runtimeType] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const createModel = useMutation({
    mutationFn: () =>
      runtimeProvidersApi.createModel(orgId, runtimeType, modelDialogProviderId, {
        scope: providerRows.find((provider) => provider.providerId === modelDialogProviderId)?.scope ?? "global",
        modelId: modelId.trim(),
        displayName: modelName.trim() || modelId.trim(),
        enabled: true,
      }),
    onSuccess: () => {
      setModelId("");
      setModelName("");
      setModelDialogProviderId("");
      void queryClient.invalidateQueries({ queryKey: ["runtime-models", orgId, runtimeType, modelDialogProviderId] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const updateModel = useMutation({
    mutationFn: () =>
      runtimeProvidersApi.updateModel(orgId, runtimeType, editingModel!.providerId, editingModel!.model.modelId, {
        displayName: modelName.trim() || editingModel!.model.modelId,
        enabled: editingModel!.model.enabled !== false,
      }),
    onSuccess: () => {
      const providerId = editingModel?.providerId;
      clearModelForm();
      if (providerId) {
        void queryClient.invalidateQueries({ queryKey: ["runtime-models", orgId, runtimeType, providerId] });
      }
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const toggleModel = useMutation({
    mutationFn: ({ model, providerId }: { model: RuntimeModel; providerId: string }) =>
      runtimeProvidersApi.updateModel(orgId, runtimeType, providerId, model.modelId, {
        enabled: model.enabled === false,
      }),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["runtime-models", orgId, runtimeType, variables.providerId] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const deleteProvider = useMutation({
    mutationFn: (provider: RuntimeProvider) => runtimeProvidersApi.deleteProvider(orgId, runtimeType, provider.providerId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runtime-providers", orgId, runtimeType] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  const deleteModel = useMutation({
    mutationFn: ({ model, providerId }: { model: RuntimeModel; providerId: string }) =>
      runtimeProvidersApi.deleteModel(orgId, runtimeType, providerId, model.modelId),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["runtime-models", orgId, runtimeType, variables.providerId] });
      void queryClient.invalidateQueries({ queryKey: ["runtime-model-options", orgId, runtimeType] });
    },
  });

  function clearProviderForm() {
    setProviderId("");
    setProviderName("");
    setBaseUrl("");
    setApiKey("");
    setProtocol(DEFAULT_PROTOCOL);
    setProviderScope("global");
    setProviderDialogOpen(false);
    setEditingProvider(null);
  }

  function clearModelForm() {
    setModelId("");
    setModelName("");
    setModelDialogProviderId("");
    setEditingModel(null);
  }

  function openProviderEdit(provider: RuntimeProvider) {
    setEditingProvider(provider);
    setProviderDialogOpen(false);
    setProviderId(provider.providerId);
    setProviderName(provider.name ?? "");
    setBaseUrl(provider.baseUrl ?? "");
    setApiKey("");
    setProtocol(provider.protocol ?? DEFAULT_PROTOCOL);
    setProviderScope(provider.scope ?? "organization");
  }

  function openModelCreate(providerId: string) {
    setEditingModel(null);
    setModelId("");
    setModelName("");
    setModelDialogProviderId(providerId);
  }

  function openModelEdit(providerId: string, model: RuntimeModel) {
    setModelDialogProviderId("");
    setEditingModel({ providerId, model });
    setModelId(model.modelId);
    setModelName(model.displayName ?? "");
  }

  function confirmDeleteProvider(provider: RuntimeProvider) {
    const providerName = provider.name || provider.providerId;
    const message =
      provider.scope === "global"
        ? english
          ? `Delete global provider: ${providerName}? It may be used by multiple organizations.`
          : `确认删除全局 Provider：${providerName}？它可能被多个组织使用。`
        : english
          ? `Delete organization provider: ${providerName}?`
          : `确认删除组织 Provider：${providerName}？`;
    if (!window.confirm(message)) return;
    deleteProvider.mutate(provider);
  }

  function confirmDeleteModel(providerId: string, model: RuntimeModel) {
    const modelName = model.displayName || model.modelId;
    if (!window.confirm(english ? `Delete model: ${modelName}?` : `确认删除模型：${modelName}？`)) return;
    deleteModel.mutate({ providerId, model });
  }

  function toggleModelEnabled(providerId: string, model: RuntimeModel) {
    toggleModel.mutate({ providerId, model });
  }

  function submitProvider(event: FormEvent) {
    event.preventDefault();
    if (editingProvider) {
      updateProvider.mutate();
    } else if (providerId.trim()) {
      createProvider.mutate();
    }
  }

  function submitModel(event: FormEvent) {
    event.preventDefault();
    if (editingModel) {
      updateModel.mutate();
    } else if (modelDialogProviderId && modelId.trim()) {
      createModel.mutate();
    }
  }

  return (
    <section className="runtime-settings" aria-label="模型供应商设置">
      <div className="panel-heading runtime-provider-heading">
        <div className="settings-section-heading-copy">
          <p className="eyebrow">Runtime Providers</p>
          <div className="runtime-provider-title-line">
            <h3>{english ? "Runtime Providers" : "模型供应商"}</h3>
            <p className="muted">
              {english ? "Manage runtime providers and models for the current organization." : "维护当前组织的运行时 provider 和 model。"}
            </p>
          </div>
        </div>
        <label className="runtime-type-select">
          {english ? "Runtime" : "运行时"}
          <select
            value={runtimeType}
            onChange={(event) => {
              clearProviderForm();
              clearModelForm();
              setRuntimeType(event.target.value as AgentRuntimeType);
            }}
          >
            {MODEL_PROVIDER_RUNTIMES.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
      </div>
      <section className="runtime-settings-column runtime-provider-section">
        <div className="runtime-settings-title">
          <h4>Provider</h4>
          <div className="runtime-settings-title-actions">
            <span>{providerRows.length}</span>
            <button className="secondary small-button" onClick={() => setProviderDialogOpen(true)} type="button">
              {english ? "New Provider" : "新建 Provider"}
            </button>
          </div>
        </div>
        <div className="runtime-provider-list runtime-provider-group-list">
          {providerRows.map((provider) => (
            <ProviderModelGroup
              key={provider.providerId}
              onCreateModel={() => openModelCreate(provider.providerId)}
              onDeleteModel={(model) => confirmDeleteModel(provider.providerId, model)}
              onDeleteProvider={() => confirmDeleteProvider(provider)}
              onEditModel={(model) => openModelEdit(provider.providerId, model)}
              onEditProvider={() => openProviderEdit(provider)}
              onToggleModel={(model) => toggleModelEnabled(provider.providerId, model)}
              onToggleProvider={() => toggleProvider.mutate(provider)}
              orgId={orgId}
              provider={provider}
              runtimeType={runtimeType}
            />
          ))}
        </div>
      </section>
      {providers.error && <ErrorNotice error={providers.error} />}
      {deleteProvider.error && <ErrorNotice error={deleteProvider.error} />}
      {deleteModel.error && <ErrorNotice error={deleteModel.error} />}
      {toggleProvider.error && <ErrorNotice error={toggleProvider.error} />}
      {toggleModel.error && <ErrorNotice error={toggleModel.error} />}
      {providerDialogOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setProviderDialogOpen(false);
          }}
          role="presentation"
        >
          <section aria-label="新建 Provider" aria-modal="true" className="panel task-modal runtime-provider-dialog" role="dialog">
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Runtime Provider</p>
                <h2>{english ? "New Provider" : "新建 Provider"}</h2>
              </div>
              <button className="secondary small-button" onClick={() => setProviderDialogOpen(false)} type="button">
                {english ? "Close" : "关闭"}
              </button>
            </div>
            <form className="runtime-settings-form" onSubmit={submitProvider}>
              <label>
                {english ? "Scope" : "作用域"}
                <select value={providerScope} onChange={(event) => setProviderScope(event.target.value as RuntimeProviderScope)}>
                  <option value="global">{english ? "Global" : "全局"}</option>
                  <option value="organization">{english ? "Organization only" : "仅当前组织"}</option>
                </select>
              </label>
              <label>
                Provider ID
                <input value={providerId} onChange={(event) => setProviderId(event.target.value)} required />
              </label>
              <label>
                {english ? "Provider name" : "Provider 名称"}
                <input value={providerName} onChange={(event) => setProviderName(event.target.value)} />
              </label>
              <label>
                {english ? "Protocol" : "协议"}
                <input value={protocol} onChange={(event) => setProtocol(event.target.value)} />
              </label>
              <label>
                Base URL
                <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
              </label>
              <label>
                API Key
                <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
              </label>
              <div className="task-modal-actions">
              <button className="secondary" onClick={clearProviderForm} type="button">{english ? "Cancel" : "取消"}</button>
                <button disabled={createProvider.isPending} type="submit">{english ? "Save Provider" : "保存 Provider"}</button>
              </div>
              {createProvider.error && <ErrorNotice error={createProvider.error} />}
            </form>
          </section>
        </div>
      )}
      {editingProvider && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) clearProviderForm();
          }}
          role="presentation"
        >
          <section aria-label="编辑 Provider" aria-modal="true" className="panel task-modal runtime-provider-dialog" role="dialog">
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Runtime Provider</p>
                <h2>{english ? "Edit Provider" : "编辑 Provider"}</h2>
                <p className="muted">{editingProvider.providerId}</p>
                <Badge>{scopeLabel(editingProvider.scope, english)}</Badge>
              </div>
              <button className="secondary small-button" onClick={clearProviderForm} type="button">
                {english ? "Close" : "关闭"}
              </button>
            </div>
            <form className="runtime-settings-form" onSubmit={submitProvider}>
              <label>
                {english ? "Scope" : "作用域"}
                <input disabled value={scopeLabel(providerScope, english)} />
              </label>
              <label>
                Provider ID
                <input disabled value={providerId} />
              </label>
              <label>
                {english ? "Provider name" : "Provider 名称"}
                <input value={providerName} onChange={(event) => setProviderName(event.target.value)} />
              </label>
              <label>
                {english ? "Protocol" : "协议"}
                <input value={protocol} onChange={(event) => setProtocol(event.target.value)} />
              </label>
              <label>
                Base URL
                <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
              </label>
              <label>
                API Key
                <input placeholder={editingProvider.hasApiKey ? (english ? "Leave blank to keep unchanged" : "留空表示不修改") : ""} value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
              </label>
              <div className="task-modal-actions">
                <button className="secondary" onClick={clearProviderForm} type="button">{english ? "Cancel" : "取消"}</button>
                <button disabled={updateProvider.isPending} type="submit">{english ? "Save Provider" : "保存 Provider"}</button>
              </div>
              {updateProvider.error && <ErrorNotice error={updateProvider.error} />}
            </form>
          </section>
        </div>
      )}
      {modelDialogProviderId && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setModelDialogProviderId("");
          }}
          role="presentation"
        >
          <section aria-label="新建 Model" aria-modal="true" className="panel task-modal runtime-provider-dialog" role="dialog">
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Runtime Model</p>
                <h2>{english ? "New Model" : "新建 Model"}</h2>
                <p className="muted">Provider: {modelDialogProviderId}</p>
                <Badge>{scopeLabel(providerRows.find((provider) => provider.providerId === modelDialogProviderId)?.scope, english)}</Badge>
              </div>
              <button className="secondary small-button" onClick={() => setModelDialogProviderId("")} type="button">
                {english ? "Close" : "关闭"}
              </button>
            </div>
            <form className="runtime-settings-form" onSubmit={submitModel}>
              <label>
                Model ID
                <input value={modelId} onChange={(event) => setModelId(event.target.value)} required />
              </label>
              <label>
                {english ? "Model display name" : "模型显示名称"}
                <input value={modelName} onChange={(event) => setModelName(event.target.value)} />
              </label>
              <div className="task-modal-actions">
              <button className="secondary" onClick={clearModelForm} type="button">{english ? "Cancel" : "取消"}</button>
                <button disabled={createModel.isPending} type="submit">{english ? "Save Model" : "保存 Model"}</button>
              </div>
              {createModel.error && <ErrorNotice error={createModel.error} />}
            </form>
          </section>
        </div>
      )}
      {editingModel && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) clearModelForm();
          }}
          role="presentation"
        >
          <section aria-label="编辑 Model" aria-modal="true" className="panel task-modal runtime-provider-dialog" role="dialog">
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Runtime Model</p>
                <h2>{english ? "Edit Model" : "编辑 Model"}</h2>
                <p className="muted">Provider: {editingModel.providerId}</p>
                <Badge>{scopeLabel(editingModel.model.scope, english)}</Badge>
              </div>
              <button className="secondary small-button" onClick={clearModelForm} type="button">
                {english ? "Close" : "关闭"}
              </button>
            </div>
            <form className="runtime-settings-form" onSubmit={submitModel}>
              <label>
                Model ID
                <input disabled value={modelId} />
              </label>
              <label>
                {english ? "Model display name" : "模型显示名称"}
                <input value={modelName} onChange={(event) => setModelName(event.target.value)} />
              </label>
              <div className="task-modal-actions">
                <button className="secondary" onClick={clearModelForm} type="button">{english ? "Cancel" : "取消"}</button>
                <button disabled={updateModel.isPending} type="submit">{english ? "Save Model" : "保存 Model"}</button>
              </div>
              {updateModel.error && <ErrorNotice error={updateModel.error} />}
            </form>
          </section>
        </div>
      )}
    </section>
  );
}

function ProviderModelGroup({
  onCreateModel,
  onDeleteModel,
  onDeleteProvider,
  onEditModel,
  onEditProvider,
  onToggleModel,
  onToggleProvider,
  orgId,
  provider,
  runtimeType,
}: {
  onCreateModel: () => void;
  onDeleteModel: (model: RuntimeModel) => void;
  onDeleteProvider: () => void;
  onEditModel: (model: RuntimeModel) => void;
  onEditProvider: () => void;
  onToggleModel: (model: RuntimeModel) => void;
  onToggleProvider: () => void;
  orgId: string;
  provider: RuntimeProvider;
  runtimeType: AgentRuntimeType;
}) {
  const models = useQuery({
    queryKey: ["runtime-models", orgId, runtimeType, provider.providerId],
    queryFn: () => runtimeProvidersApi.listModels(orgId, runtimeType, provider.providerId),
    enabled: Boolean(orgId && provider.providerId),
  });
  const providerName = provider.name || provider.providerId;
  const english = isEnglishLocale();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  function closeMenu() {
    setOpenMenu(null);
  }
  return (
    <article aria-label={`${providerName} provider`} className="runtime-provider-group">
      <div className="runtime-provider-group-header">
        <div>
          <strong>{providerName}</strong>
          <Badge>{scopeLabel(provider.scope, english)}</Badge>
          <span>{provider.providerId}</span>
          <small>{provider.baseUrl ?? (english ? "No Base URL" : "未设置 Base URL")}</small>
          <em>{provider.hasApiKey ? (english ? "API key configured" : "已配置 API Key") : (english ? "API key missing" : "未配置 API Key")}</em>
        </div>
        <div className="runtime-provider-actions">
          <div
            className="runtime-action-menu"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) closeMenu();
            }}
          >
            <button
              aria-expanded={openMenu === "provider"}
              aria-label={`${providerName} 更多操作`}
              className="icon-menu-button"
              onClick={() => setOpenMenu(openMenu === "provider" ? null : "provider")}
              type="button"
            >
              ...
            </button>
            {openMenu === "provider" && (
              <div className="runtime-action-popover" role="menu">
                <button
                  onClick={() => {
                    closeMenu();
                    onCreateModel();
                  }}
                  role="menuitem"
                  type="button"
                >
                  {english ? "New model" : "新增模型"}
                </button>
                <button
                  onClick={() => {
                    closeMenu();
                    onEditProvider();
                  }}
                  role="menuitem"
                  type="button"
                >
                  {english ? "Edit" : "编辑"}
                </button>
                <button
                  onClick={() => {
                    closeMenu();
                    onToggleProvider();
                  }}
                  role="menuitem"
                  type="button"
                >
                  {provider.enabled === false ? (english ? "Enable" : "启用") : (english ? "Disable" : "禁用")}
                </button>
                <button
                  className="danger"
                  onClick={() => {
                    closeMenu();
                    onDeleteProvider();
                  }}
                  role="menuitem"
                  type="button"
                >
                  {english ? "Delete" : "删除"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="runtime-model-list compact">
        {(models.data ?? []).map((model) => (
          <article key={model.modelId}>
            <div className="runtime-model-row-content">
              <div className="runtime-model-row-main">
                <div className="runtime-model-title-line">
                  <strong>{model.displayName || model.modelId}</strong>
                  <Badge>{model.enabled === false ? (english ? "disabled" : "已禁用") : (english ? "enabled" : "已启用")}</Badge>
                  <Badge>{scopeLabel(model.scope ?? provider.scope, english)}</Badge>
                </div>
                <div className="runtime-model-actions">
                  <button
                    aria-label={model.enabled === false ? (english ? "Enable" : "启用") : (english ? "Disable" : "禁用")}
                    className="secondary icon-action-button small-button"
                    onClick={() => onToggleModel(model)}
                    title={model.enabled === false ? (english ? "Enable" : "启用") : (english ? "Disable" : "禁用")}
                    type="button"
                  >
                    <span aria-hidden="true">{model.enabled === false ? "▶" : "⏸"}</span>
                  </button>
                  <button
                    aria-label={english ? "Edit" : "编辑"}
                    className="secondary icon-action-button small-button"
                    onClick={() => onEditModel(model)}
                    title={english ? "Edit" : "编辑"}
                    type="button"
                  >
                    <span aria-hidden="true">✎</span>
                  </button>
                  <button
                    aria-label={english ? "Delete" : "删除"}
                    className="secondary danger icon-action-button small-button"
                    onClick={() => onDeleteModel(model)}
                    title={english ? "Delete" : "删除"}
                    type="button"
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </div>
              </div>
              <span className="runtime-model-id">{model.modelId}</span>
            </div>
          </article>
        ))}
      </div>
      {models.error && <ErrorNotice error={models.error} />}
    </article>
  );
}

function scopeLabel(scope: RuntimeProviderScope | undefined, _english: boolean) {
  if (scope === "global") return "Global";
  return "Organization";
}
