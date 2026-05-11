NAMESPACE     ?= maas-demo
REGISTRY      ?= image-registry.openshift-image-registry.svc:5000/$(NAMESPACE)
TAG           ?= latest

.PHONY: build push deploy all secrets

all: build push deploy

## Build all container images
build:
	podman build -t $(REGISTRY)/mcp-server:$(TAG) ./mcp-server
	podman build -t $(REGISTRY)/backend:$(TAG) ./backend
	podman build -t $(REGISTRY)/frontend:$(TAG) ./frontend

## Push images to OpenShift internal registry
push:
	podman push $(REGISTRY)/mcp-server:$(TAG)
	podman push $(REGISTRY)/backend:$(TAG)
	podman push $(REGISTRY)/frontend:$(TAG)

## Apply all manifests to the cluster
deploy:
	oc apply -k .

## Show frontend Route URL
url:
	@oc get route frontend -n $(NAMESPACE) -o jsonpath='{.spec.host}' && echo

## Tail BFF logs
logs-backend:
	oc logs -n $(NAMESPACE) -l app=backend -f

## Tail MCP server logs
logs-mcp:
	oc logs -n $(NAMESPACE) -l app=mcp-server -f

## Delete all demo resources (keeps namespace)
clean:
	oc delete -k . --ignore-not-found
