# nuc-kserve — Best Practice Guide

**nuc-kserve** manages KServe CRD resources: InferenceServices, InferenceGraphs, LocalModelCaches, TrainedModels, and ClusterServingRuntimes / ServingRuntimes.

**Prerequisite:** KServe must be installed in the cluster, typically alongside Knative Serving and Istio.

## Enable

```yaml
nuc-kserve:
  enabled: true
```

## InferenceServices

### Pre-built framework predictors

KServe provides built-in serving runtimes for common ML frameworks:

#### scikit-learn

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    sklearn-model:
      spec:
        predictor:
          sklearn:
            storageUri: s3://models/sklearn-iris
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                cpu: 500m
                memory: 1Gi
```

#### TensorFlow

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    tf-model:
      spec:
        predictor:
          tensorflow:
            storageUri: s3://models/tf-resnet
            runtimeVersion: "2.14.0"
```

#### PyTorch (TorchServe)

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    pytorch-model:
      spec:
        predictor:
          pytorch:
            storageUri: s3://models/pytorch-bert
```

#### Hugging Face (LLM inference)

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    llm:
      spec:
        predictor:
          huggingface:
            storageUri: s3://models/llm-7b
            args:
              - --model_name=llm
              - --max_length=512
            resources:
              requests:
                memory: 16Gi
                nvidia.com/gpu: "1"
              limits:
                memory: 32Gi
                nvidia.com/gpu: "1"
```

### Custom container

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    custom-model:
      spec:
        predictor:
          containers:
            - name: model-server
              image: my-org/model-server:1.0.0
              ports:
                - containerPort: 8080
                  protocol: TCP
              env:
                - name: MODEL_PATH
                  value: /mnt/models/model.pkl
              volumeMounts:
                - mountPath: /mnt/models
                  name: model-volume
          volumes:
            - name: model-volume
              persistentVolumeClaim:
                claimName: model-pvc
```

### With transformer (pre/post-processing)

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    model-with-transformer:
      spec:
        transformer:
          containers:
            - name: transformer
              image: my-org/transformer:1.0.0
              ports:
                - containerPort: 8080
        predictor:
          sklearn:
            storageUri: s3://models/sklearn-model
```

### Canary rollout

```yaml
nuc-kserve:
  enabled: true
  inferenceServices:
    model:
      spec:
        predictor:
          sklearn:
            storageUri: s3://models/sklearn-v2
        canaryTrafficPercent: 20    # 20% to new version, 80% to stable
```

## InferenceGraphs

Route requests across multiple InferenceServices:

```yaml
nuc-kserve:
  enabled: true
  inferenceGraphs:
    ensemble:
      spec:
        nodes:
          root:
            routerType: Ensemble
            steps:
              - serviceName: model-a
                weight: 50
              - serviceName: model-b
                weight: 50
```

## LocalModelCaches

Pre-download models to nodes for fast cold starts:

```yaml
nuc-kserve:
  enabled: true
  localModelCaches:
    sklearn-iris:
      spec:
        modelSize: 500Mi
        nodeGroup: gpu-nodes
        sourceModelUri: s3://models/sklearn-iris
```

## ServingRuntimes (custom runtimes)

```yaml
nuc-kserve:
  enabled: true
  servingRuntimes:
    custom-runtime:
      spec:
        supportedModelFormats:
          - name: custom-format
            version: "1"
            autoSelect: true
        protocolVersions:
          - v2
        containers:
          - name: runtime
            image: my-org/custom-runtime:1.0.0
            args:
              - --model_name={{.Name}}
              - --http_port=8080
            ports:
              - containerPort: 8080
                protocol: TCP
```

## Best practices

- **Use S3-compatible object storage** for `storageUri` — KServe's storage initializer downloads the model at pod startup; local PVCs are an alternative for frequently-used models.
- **Use LocalModelCaches** for large models (>1GB) to pre-download to GPU nodes — eliminates the per-pod download latency on scale-out.
- **Set resource requests and limits** for GPU workloads explicitly (`nvidia.com/gpu: "1"`) — Kubernetes requires explicit GPU resource requests to schedule on GPU nodes.
- **Use canary rollout** (`canaryTrafficPercent`) to gradually shift traffic to new model versions — test new models under real load before full promotion.
- **Use InferenceGraphs** for ensemble and pipeline architectures instead of chaining calls in application code — the graph handles routing, aggregation, and error handling.
- **Combine with nuc-knative** — KServe builds on Knative Serving for serverless inference; ensure Knative is configured with appropriate scale-to-zero settings for your SLA.
- **Combine with nuc-istio** — use Istio for mTLS between services and Istio Gateway for external access to InferenceService endpoints.
