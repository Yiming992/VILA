# Copyright 2024 NVIDIA CORPORATION & AFFILIATES
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

import torch


def _cast_if_autocast_enabled(tensor):
    if torch.is_autocast_enabled():
        if tensor.device.type == "cuda":
            dtype = torch.get_autocast_gpu_dtype()
        elif tensor.device.type == "cpu":
            dtype = torch.get_autocast_cpu_dtype()
        else:
            raise NotImplementedError()
        return tensor.to(dtype=dtype)
    return tensor


class LPLayerNorm(torch.nn.LayerNorm):
    def __init__(self, normalized_shape, eps=1e-05, elementwise_affine=True, device=None, dtype=None):
        super().__init__(
            normalized_shape=normalized_shape,
            eps=eps,
            elementwise_affine=elementwise_affine,
            device=device,
            dtype=dtype,
        )

    def forward(self, x):
        module_device = x.device
        downcast_x = _cast_if_autocast_enabled(x)
        downcast_weight = _cast_if_autocast_enabled(self.weight) if self.weight is not None else self.weight
        downcast_bias = _cast_if_autocast_enabled(self.bias) if self.bias is not None else self.bias
        with torch.autocast(enabled=False, device_type=module_device.type):
            return torch.nn.functional.layer_norm(
                downcast_x, self.normalized_shape, downcast_weight, downcast_bias, self.eps
            )


def rms_norm(x, weight=None, eps=1e-05):
    output = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + eps)
    if weight is not None:
        return output * weight
    return output


class RMSNorm(torch.nn.Module):
    def __init__(self, normalized_shape, eps=1e-05, weight=True, dtype=None, device=None):
        super().__init__()
        self.eps = eps
        if weight:
            self.weight = torch.nn.Parameter(torch.ones(normalized_shape, dtype=dtype, device=device))
        else:
            self.register_parameter("weight", None)

    def forward(self, x):
        return rms_norm(x.float(), self.weight, self.eps).to(dtype=x.dtype)


class LPRMSNorm(RMSNorm):
    def __init__(self, normalized_shape, eps=1e-05, weight=True, dtype=None, device=None):
        super().__init__(normalized_shape=normalized_shape, eps=eps, weight=weight, dtype=dtype, device=device)

    def forward(self, x):
        downcast_x = _cast_if_autocast_enabled(x)
        downcast_weight = _cast_if_autocast_enabled(self.weight) if self.weight is not None else self.weight
        with torch.autocast(enabled=False, device_type=x.device.type):
            return rms_norm(downcast_x, downcast_weight, self.eps).to(dtype=x.dtype)


NORM_CLASS_REGISTRY = {
    "layernorm": torch.nn.LayerNorm,
    "low_precision_layernorm": LPLayerNorm,
    "rmsnorm": RMSNorm,
    "low_precision_rmsnorm": LPRMSNorm,
}
