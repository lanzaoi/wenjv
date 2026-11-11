declare module 'onnxruntime-node' {
  export interface SessionOptions {
    intraOpNumThreads?: number;
    interOpNumThreads?: number;
    graphOptimizationLevel?: 'disabled' | 'basic' | 'extended' | 'all';
    executionProviders?: Array<string | { name: string; [key: string]: unknown }>;
  }

  export class Tensor {
    constructor(type: string, data: unknown, dims?: readonly number[]);
    data: unknown;
    dims: readonly number[];
    type: string;
    size: number;
  }

  export class InferenceSession {
    static create(
      uriOrBuffer: string | ArrayBufferLike | Uint8Array,
      options?: SessionOptions
    ): Promise<InferenceSession>;

    run(
      feeds: Record<string, Tensor>,
      fetches?: Record<string, unknown> | readonly string[],
      options?: Record<string, unknown>
    ): Promise<Record<string, Tensor>>;

    inputNames: readonly string[];
    outputNames: readonly string[];
  }

  const ort: {
    InferenceSession: typeof InferenceSession;
    Tensor: typeof Tensor;
  };

  export default ort;
}

declare namespace ort {
  export type InferenceSession = import('onnxruntime-node').InferenceSession;
  export type SessionOptions = import('onnxruntime-node').SessionOptions;
  export type Tensor = import('onnxruntime-node').Tensor;
}
