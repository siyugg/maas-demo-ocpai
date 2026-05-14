NAMESPACE     ?= maas-demo
REGISTRY      ?= image-registry.openshift-image-registry.svc:5000/$(NAMESPACE)
TAG           ?= latest

.PHONY: build push deploy all buildconfig build-ocp build-ocp-backend build-ocp-frontend build-ocp-mcp

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

## Apply BuildConfigs + ImageStreams (OpenShift-native in-cluster builds)
buildconfig:
	oc apply -f openshift/build/imagestreams.yaml -n $(NAMESPACE)
	oc apply -f openshift/build/buildconfigs.yaml -n $(NAMESPACE)

## Trigger all OpenShift binary builds from local source (one command after each change)
build-ocp: buildconfig build-ocp-mcp build-ocp-backend build-ocp-frontend

build-ocp-mcp:
	oc start-build mcp-server -n $(NAMESPACE) --from-dir=./mcp-server --follow --wait

build-ocp-backend:
	oc start-build backend -n $(NAMESPACE) --from-dir=./backend --follow --wait

build-ocp-frontend:
	oc start-build frontend -n $(NAMESPACE) --from-dir=./frontend --follow --wait

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
